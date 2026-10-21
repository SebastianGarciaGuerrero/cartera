"""Fase 3: ciclo de vida de la cobranza y módulo judicial.

Ciclo de vida
  - `cobranzas.etapa`: ingreso → extrajudicial → para_demanda → judicial.
    El término no es una etapa: sale del estado (pagada / archivada /
    castigo), con su `motivo_cierre`. De judicial no se vuelve atrás (lo
    impide un trigger: hay una demanda de por medio).
  - `cambios_etapa`: historial de cada paso (quién, cuándo, por qué).
  - La primera gestión de una cobranza en ingreso la pasa sola a
    extrajudicial (trigger en `gestiones`).
  - `clientes.dias_para_demanda`: a los cuántos días desde el ingreso el
    sistema sugiere preparar la demanda (NULL = sin sugerencia, 0 = de
    inmediato). La decisión la toma siempre una persona.
  - `cobranzas.estudio_a_cargo`: corresponsal que lleva el caso (por ahora
    sin pantalla, queda disponible para cuando se necesite).

Judicial
  - `tribunales` y `tipos_tramite`: catálogos mixtos (filas de sistema con
    organizacion_id NULL + propias). Los trámites traen plazo de
    seguimiento, trámite siguiente, si generan gasto y si son alerta.
  - `causas`: una demanda (un rol en un tribunal). Puede incluir varias
    cobranzas del mismo deudor y cliente (`causa_cobranzas`).
  - `tramites`: lo que pasa en la causa. Inmutable como las gestiones. El
    plazo pendiente de una causa es el del último trámite con tipo.
  - `embargos`: bienes trabados y su estado (editable: el embargo avanza).
  - `gastos` y `rendiciones_gastos`: lo que paga el estudio y le cobra
    después al mandante (por rendir → rendido → reembolsado).

La ficha judicial antigua (`gestiones_judiciales`, 1 a 1 con la cobranza y
con el estado en texto libre) se copia a `causas` y deja de usarse.

Revisión: 0010
"""

from alembic import op
from sqlalchemy import text

from migraciones.datos_judicial import TRAMITES, TRIBUNALES
from migraciones.utilidades import ROL_APP, proteger_tabla_tenant

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

HOY_CHILE = "fecha_chile()"


def upgrade() -> None:
    bind = op.get_bind()

    # Fecha de hoy en Chile (de noche en UTC ya es mañana). Si el servidor no
    # trae la base de zonas horarias (Postgres portátil de los tests), se
    # aproxima con UTC-4.
    op.execute("""
        CREATE FUNCTION fecha_chile() RETURNS date
        LANGUAGE plpgsql STABLE AS $$
        BEGIN
            RETURN (NOW() AT TIME ZONE 'America/Santiago')::date;
        EXCEPTION WHEN invalid_parameter_value THEN
            RETURN (NOW() AT TIME ZONE 'UTC' - INTERVAL '4 hours')::date;
        END $$
    """)
    op.execute(f"GRANT EXECUTE ON FUNCTION fecha_chile() TO {ROL_APP}")

    # ------------------------------------------------------------ ciclo de vida
    op.execute(f"""
        ALTER TABLE cobranzas
            ADD COLUMN etapa           VARCHAR(20) NOT NULL DEFAULT 'ingreso'
                CHECK (etapa IN ('ingreso', 'extrajudicial', 'para_demanda', 'judicial')),
            ADD COLUMN etapa_desde     DATE        NOT NULL DEFAULT {HOY_CHILE},
            ADD COLUMN motivo_cierre   VARCHAR(30),
            ADD COLUMN fecha_cierre    DATE,
            ADD COLUMN estudio_a_cargo VARCHAR(150)
    """)
    # Cartera existente: lo judicial queda judicial; con gestiones, extrajudicial.
    op.execute("""
        UPDATE cobranzas c SET etapa = CASE
            WHEN c.tipo = 'judicial' OR c.estado = 'judicial'
                 OR EXISTS (SELECT 1 FROM gestiones_judiciales gj WHERE gj.cobranza_id = c.id)
                THEN 'judicial'
            WHEN EXISTS (SELECT 1 FROM gestiones g WHERE g.cobranza_id = c.id) THEN 'extrajudicial'
            ELSE 'ingreso' END,
            etapa_desde = COALESCE(c.fecha_traspaso, c.fecha_ingreso, CURRENT_DATE)
    """)
    op.execute("""
        CREATE INDEX idx_cobranzas_org_etapa ON cobranzas (organizacion_id, etapa)
            WHERE estado IN ('activa', 'acuerdo_pago', 'judicial')
    """)
    op.execute("ALTER TABLE clientes ADD COLUMN dias_para_demanda INTEGER CHECK (dias_para_demanda >= 0)")

    op.execute("""
        CREATE TABLE cambios_etapa (
            id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            organizacion_id UUID         NOT NULL REFERENCES organizaciones(id),
            cobranza_id     UUID         NOT NULL,
            etapa_anterior  VARCHAR(20),
            etapa_nueva     VARCHAR(20)  NOT NULL,
            usuario_id      UUID,
            motivo          VARCHAR(300),
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            CONSTRAINT fk_cambios_etapa_cobranza FOREIGN KEY (organizacion_id, cobranza_id)
                REFERENCES cobranzas (organizacion_id, id),
            CONSTRAINT fk_cambios_etapa_usuario FOREIGN KEY (organizacion_id, usuario_id)
                REFERENCES usuarios (organizacion_id, id)
        )
    """)
    op.execute("CREATE INDEX idx_cambios_etapa_cobranza ON cambios_etapa (cobranza_id, created_at)")
    proteger_tabla_tenant("cambios_etapa", permisos="SELECT, INSERT")

    # Cada cambio de etapa: fecha de entrada, regla de no volver y su historial.
    # Quién y por qué llegan por set_config (app/ciclo.py) o desde la gestión.
    op.execute(f"""
        CREATE FUNCTION cobranza_cambio_etapa() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.etapa IS NOT DISTINCT FROM OLD.etapa THEN
                RETURN NEW;
            END IF;
            IF OLD.etapa = 'judicial' THEN
                RAISE EXCEPTION 'Una cobranza en etapa judicial no puede volver a %', NEW.etapa
                    USING ERRCODE = 'check_violation';
            END IF;
            NEW.etapa_desde := {HOY_CHILE};
            INSERT INTO cambios_etapa (organizacion_id, cobranza_id, etapa_anterior, etapa_nueva,
                                       usuario_id, motivo)
            VALUES (NEW.organizacion_id, NEW.id, OLD.etapa, NEW.etapa,
                    NULLIF(current_setting('app.usuario_id', true), '')::uuid,
                    NULLIF(current_setting('app.motivo_etapa', true), ''));
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER trg_cobranzas_etapa BEFORE UPDATE OF etapa ON cobranzas
            FOR EACH ROW EXECUTE FUNCTION cobranza_cambio_etapa()
    """)
    op.execute("""
        CREATE FUNCTION gestion_inicia_extrajudicial() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF EXISTS (SELECT 1 FROM cobranzas WHERE id = NEW.cobranza_id AND etapa = 'ingreso') THEN
                PERFORM set_config('app.usuario_id', NEW.usuario_id::text, true);
                PERFORM set_config('app.motivo_etapa', 'Primera gestión registrada', true);
                UPDATE cobranzas SET etapa = 'extrajudicial'
                    WHERE id = NEW.cobranza_id AND etapa = 'ingreso';
                PERFORM set_config('app.motivo_etapa', '', true);
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER trg_gestiones_extrajudicial AFTER INSERT ON gestiones
            FOR EACH ROW EXECUTE FUNCTION gestion_inicia_extrajudicial()
    """)
    for funcion in ("cobranza_cambio_etapa()", "gestion_inicia_extrajudicial()"):
        op.execute(f"GRANT EXECUTE ON FUNCTION {funcion} TO {ROL_APP}")

    # ------------------------------------------------------------- catálogos
    op.execute("""
        CREATE TABLE tribunales (
            id              SERIAL       PRIMARY KEY,
            organizacion_id UUID         REFERENCES organizaciones(id),
            nombre          VARCHAR(150) NOT NULL,
            ciudad          VARCHAR(80),
            competencia     VARCHAR(20)  NOT NULL DEFAULT 'civil'
                CHECK (competencia IN ('civil', 'penal', 'laboral', 'corte', 'otro')),
            activo          BOOLEAN      NOT NULL DEFAULT TRUE
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX uq_tribunales_nombre
            ON tribunales (COALESCE(organizacion_id, '00000000-0000-0000-0000-000000000000'::uuid), lower(nombre))
    """)
    proteger_tabla_tenant("tribunales", lectura_global=True)
    op.execute(f"GRANT USAGE ON SEQUENCE tribunales_id_seq TO {ROL_APP}")
    for nombre, ciudad, competencia in TRIBUNALES:
        bind.execute(
            text("INSERT INTO tribunales (nombre, ciudad, competencia) VALUES (:n, :c, :k)"),
            {"n": nombre, "c": ciudad, "k": competencia},
        )

    op.execute("""
        CREATE TABLE tipos_tramite (
            id              SERIAL       PRIMARY KEY,
            organizacion_id UUID         REFERENCES organizaciones(id),
            codigo          VARCHAR(40),
            nombre          VARCHAR(150) NOT NULL,
            etapa           VARCHAR(20)
                CHECK (etapa IN ('demanda', 'notificacion', 'embargo', 'defensa', 'remate')),
            plazo_dias      INTEGER      CHECK (plazo_dias >= 0),
            siguiente_id    INTEGER      REFERENCES tipos_tramite(id),
            genera_gasto    BOOLEAN      NOT NULL DEFAULT FALSE,
            alerta          BOOLEAN      NOT NULL DEFAULT FALSE,
            nota            VARCHAR(300),
            resultado       VARCHAR(30),
            orden           INTEGER      NOT NULL DEFAULT 0,
            activo          BOOLEAN      NOT NULL DEFAULT TRUE
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX uq_tipos_tramite_codigo ON tipos_tramite (codigo)
            WHERE codigo IS NOT NULL AND organizacion_id IS NULL
    """)
    proteger_tabla_tenant("tipos_tramite", lectura_global=True)
    op.execute(f"GRANT USAGE ON SEQUENCE tipos_tramite_id_seq TO {ROL_APP}")
    for orden, (codigo, nombre, etapa, plazo, _sig, gasto, alerta, nota, resultado) in enumerate(TRAMITES):
        bind.execute(text("""
            INSERT INTO tipos_tramite (codigo, nombre, etapa, plazo_dias, genera_gasto, alerta,
                                       nota, resultado, orden)
            VALUES (:codigo, :nombre, :etapa, :plazo, :gasto, :alerta, :nota, :resultado, :orden)
        """), {"codigo": codigo, "nombre": nombre, "etapa": etapa, "plazo": plazo, "gasto": gasto,
               "alerta": alerta, "nota": nota, "resultado": resultado, "orden": orden})
    for codigo, *_resto in TRAMITES:
        siguiente = _resto[3]
        if siguiente:
            bind.execute(text("""
                UPDATE tipos_tramite SET siguiente_id =
                    (SELECT id FROM tipos_tramite WHERE codigo = :sig AND organizacion_id IS NULL)
                WHERE codigo = :codigo AND organizacion_id IS NULL
            """), {"sig": siguiente, "codigo": codigo})

    # ---------------------------------------------------------------- causas
    op.execute("""
        CREATE TABLE causas (
            id              UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
            organizacion_id UUID          NOT NULL REFERENCES organizaciones(id),
            cliente_id      UUID          NOT NULL,
            deudor_id       UUID          NOT NULL,
            rol             VARCHAR(40),
            tribunal_id     INTEGER       REFERENCES tribunales(id),
            procedimiento   VARCHAR(30)   NOT NULL DEFAULT 'ejecutivo'
                CHECK (procedimiento IN ('ejecutivo', 'notificacion_cheque', 'notificacion_factura',
                                         'notificacion_letra', 'confesion_deuda', 'ordinario',
                                         'sumario', 'exhorto', 'liquidacion', 'querella', 'otro')),
            etapa_procesal  VARCHAR(20)   NOT NULL DEFAULT 'demanda'
                CHECK (etapa_procesal IN ('demanda', 'notificacion', 'embargo', 'defensa', 'remate')),
            estado          VARCHAR(20)   NOT NULL DEFAULT 'vigente'
                CHECK (estado IN ('vigente', 'terminada')),
            resultado       VARCHAR(30),
            fecha_ingreso   DATE          NOT NULL DEFAULT CURRENT_DATE,
            fecha_termino   DATE,
            cuantia         NUMERIC(15,2),
            caratula        VARCHAR(250),
            abogado_id      UUID,
            procurador_id   UUID,
            observaciones   TEXT,
            creado_por      UUID          NOT NULL,
            created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_causas_org_id UNIQUE (organizacion_id, id),
            CONSTRAINT fk_causas_cliente FOREIGN KEY (organizacion_id, cliente_id)
                REFERENCES clientes (organizacion_id, id),
            CONSTRAINT fk_causas_deudor FOREIGN KEY (organizacion_id, deudor_id)
                REFERENCES deudores (organizacion_id, id),
            CONSTRAINT fk_causas_abogado FOREIGN KEY (organizacion_id, abogado_id)
                REFERENCES usuarios (organizacion_id, id),
            CONSTRAINT fk_causas_procurador FOREIGN KEY (organizacion_id, procurador_id)
                REFERENCES usuarios (organizacion_id, id),
            CONSTRAINT fk_causas_creador FOREIGN KEY (organizacion_id, creado_por)
                REFERENCES usuarios (organizacion_id, id),
            CONSTRAINT ck_causas_termino CHECK ((estado = 'terminada') = (fecha_termino IS NOT NULL))
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX uq_causas_rol ON causas (organizacion_id, tribunal_id, upper(rol))
            WHERE rol IS NOT NULL AND tribunal_id IS NOT NULL
    """)
    op.execute("CREATE INDEX idx_causas_org_estado ON causas (organizacion_id, estado, etapa_procesal)")
    op.execute("CREATE INDEX idx_causas_deudor ON causas (deudor_id)")
    proteger_tabla_tenant("causas")

    op.execute("""
        CREATE TABLE causa_cobranzas (
            organizacion_id UUID        NOT NULL REFERENCES organizaciones(id),
            causa_id        UUID        NOT NULL,
            cobranza_id     UUID        NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (causa_id, cobranza_id),
            CONSTRAINT fk_causa_cobranzas_causa FOREIGN KEY (organizacion_id, causa_id)
                REFERENCES causas (organizacion_id, id),
            CONSTRAINT fk_causa_cobranzas_cobranza FOREIGN KEY (organizacion_id, cobranza_id)
                REFERENCES cobranzas (organizacion_id, id)
        )
    """)
    op.execute("CREATE INDEX idx_causa_cobranzas_cobranza ON causa_cobranzas (cobranza_id)")
    proteger_tabla_tenant("causa_cobranzas", permisos="SELECT, INSERT")

    op.execute("""
        CREATE TABLE tramites (
            id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            organizacion_id UUID         NOT NULL REFERENCES organizaciones(id),
            causa_id        UUID         NOT NULL,
            tipo_id         INTEGER      REFERENCES tipos_tramite(id),   -- NULL = observación
            fecha           DATE         NOT NULL,
            descripcion     TEXT,
            plazo_fecha     DATE,                                        -- revisar a más tardar
            siguiente_id    INTEGER      REFERENCES tipos_tramite(id),   -- trámite esperado
            usuario_id      UUID         NOT NULL,
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_tramites_org_id UNIQUE (organizacion_id, id),
            CONSTRAINT fk_tramites_causa FOREIGN KEY (organizacion_id, causa_id)
                REFERENCES causas (organizacion_id, id),
            CONSTRAINT fk_tramites_usuario FOREIGN KEY (organizacion_id, usuario_id)
                REFERENCES usuarios (organizacion_id, id),
            CONSTRAINT ck_tramites_contenido CHECK (tipo_id IS NOT NULL OR descripcion IS NOT NULL)
        )
    """)
    op.execute("CREATE INDEX idx_tramites_causa_fecha ON tramites (causa_id, fecha DESC, created_at DESC)")
    # Inmutable como las gestiones: sin UPDATE para la app y, aun como dueño,
    # el trigger lo impide.
    proteger_tabla_tenant("tramites", permisos="SELECT, INSERT")
    for tabla in ("tramites", "cambios_etapa"):
        op.execute(f"""
            CREATE TRIGGER trg_{tabla}_inmutable BEFORE UPDATE OR DELETE ON {tabla}
                FOR EACH ROW EXECUTE FUNCTION impedir_modificacion()
        """)

    op.execute("""
        CREATE TABLE embargos (
            id              UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
            organizacion_id UUID          NOT NULL REFERENCES organizaciones(id),
            causa_id        UUID          NOT NULL,
            tipo_bien       VARCHAR(20)   NOT NULL
                CHECK (tipo_bien IN ('vehiculo', 'inmueble', 'cuenta_bancaria', 'remuneraciones',
                                     'muebles', 'otro')),
            descripcion     VARCHAR(300)  NOT NULL,
            estado          VARCHAR(20)   NOT NULL DEFAULT 'trabado'
                CHECK (estado IN ('solicitado', 'trabado', 'frustrado', 'retirado', 'rematado', 'alzado')),
            fecha_traba     DATE,
            inscripcion     VARCHAR(150),
            depositario     VARCHAR(150),
            monto_tasacion  NUMERIC(15,2) CHECK (monto_tasacion >= 0),
            fecha_remate    DATE,
            monto_remate    NUMERIC(15,2) CHECK (monto_remate >= 0),
            observaciones   TEXT,
            creado_por      UUID          NOT NULL,
            created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
            CONSTRAINT fk_embargos_causa FOREIGN KEY (organizacion_id, causa_id)
                REFERENCES causas (organizacion_id, id),
            CONSTRAINT fk_embargos_creador FOREIGN KEY (organizacion_id, creado_por)
                REFERENCES usuarios (organizacion_id, id)
        )
    """)
    op.execute("CREATE INDEX idx_embargos_causa ON embargos (causa_id)")
    proteger_tabla_tenant("embargos")

    # ---------------------------------------------------------------- gastos
    op.execute("""
        CREATE TABLE rendiciones_gastos (
            id              UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
            organizacion_id UUID          NOT NULL REFERENCES organizaciones(id),
            numero          INTEGER       NOT NULL,
            cliente_id      UUID          NOT NULL,
            fecha           DATE          NOT NULL,
            total           NUMERIC(15,2) NOT NULL CHECK (total >= 0),
            estado          VARCHAR(20)   NOT NULL DEFAULT 'enviada'
                CHECK (estado IN ('enviada', 'pagada', 'anulada')),
            fecha_pago      DATE,
            observaciones   TEXT,
            creado_por      UUID          NOT NULL,
            created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_rendiciones_org_id UNIQUE (organizacion_id, id),
            CONSTRAINT uq_rendiciones_numero UNIQUE (organizacion_id, numero),
            CONSTRAINT fk_rendiciones_cliente FOREIGN KEY (organizacion_id, cliente_id)
                REFERENCES clientes (organizacion_id, id),
            CONSTRAINT fk_rendiciones_creador FOREIGN KEY (organizacion_id, creado_por)
                REFERENCES usuarios (organizacion_id, id)
        )
    """)
    proteger_tabla_tenant("rendiciones_gastos")

    op.execute("""
        CREATE TABLE gastos (
            id              UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
            organizacion_id UUID          NOT NULL REFERENCES organizaciones(id),
            cliente_id      UUID          NOT NULL,
            cobranza_id     UUID,
            causa_id        UUID,
            tramite_id      UUID,
            fecha           DATE          NOT NULL,
            tipo            VARCHAR(20)   NOT NULL DEFAULT 'receptor'
                CHECK (tipo IN ('receptor', 'notificacion', 'embargo', 'fuerza_publica', 'conservador',
                                'copias', 'publicacion', 'martillero', 'correo', 'otro')),
            concepto        VARCHAR(200)  NOT NULL,
            monto           NUMERIC(15,2) NOT NULL CHECK (monto > 0),
            proveedor       VARCHAR(150),
            numero_boleta   VARCHAR(50),
            estado          VARCHAR(20)   NOT NULL DEFAULT 'por_rendir'
                CHECK (estado IN ('por_rendir', 'rendido', 'reembolsado', 'no_reembolsable', 'anulado')),
            rendicion_id    UUID,
            fecha_reembolso DATE,
            observaciones   TEXT,
            usuario_id      UUID          NOT NULL,
            created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
            CONSTRAINT fk_gastos_cliente FOREIGN KEY (organizacion_id, cliente_id)
                REFERENCES clientes (organizacion_id, id),
            CONSTRAINT fk_gastos_cobranza FOREIGN KEY (organizacion_id, cobranza_id)
                REFERENCES cobranzas (organizacion_id, id),
            CONSTRAINT fk_gastos_causa FOREIGN KEY (organizacion_id, causa_id)
                REFERENCES causas (organizacion_id, id),
            CONSTRAINT fk_gastos_tramite FOREIGN KEY (organizacion_id, tramite_id)
                REFERENCES tramites (organizacion_id, id),
            CONSTRAINT fk_gastos_rendicion FOREIGN KEY (organizacion_id, rendicion_id)
                REFERENCES rendiciones_gastos (organizacion_id, id),
            CONSTRAINT fk_gastos_usuario FOREIGN KEY (organizacion_id, usuario_id)
                REFERENCES usuarios (organizacion_id, id),
            CONSTRAINT ck_gastos_destino CHECK (cobranza_id IS NOT NULL OR causa_id IS NOT NULL),
            CONSTRAINT ck_gastos_rendicion CHECK (rendicion_id IS NULL OR estado IN ('rendido', 'reembolsado'))
        )
    """)
    op.execute("CREATE INDEX idx_gastos_org_cliente_estado ON gastos (organizacion_id, cliente_id, estado)")
    op.execute("CREATE INDEX idx_gastos_causa ON gastos (causa_id)")
    op.execute("CREATE INDEX idx_gastos_cobranza ON gastos (cobranza_id)")
    proteger_tabla_tenant("gastos")

    # --------------------------------------------- ficha judicial antigua
    # Cada ficha pasa a ser una causa con su cobranza. El tribunal en texto
    # libre se vuelve un tribunal propio de la organización.
    op.execute("""
        INSERT INTO tribunales (organizacion_id, nombre)
        SELECT DISTINCT gj.organizacion_id, left(trim(gj.tribunal), 150)
        FROM gestiones_judiciales gj
        WHERE trim(coalesce(gj.tribunal, '')) <> ''
          AND NOT EXISTS (SELECT 1 FROM tribunales t
                          WHERE lower(t.nombre) = lower(trim(gj.tribunal))
                            AND (t.organizacion_id IS NULL OR t.organizacion_id = gj.organizacion_id))
    """)
    op.execute("""
        INSERT INTO causas (id, organizacion_id, cliente_id, deudor_id, rol, tribunal_id, fecha_ingreso,
                            abogado_id, observaciones, creado_por, created_at, updated_at)
        SELECT gj.id, gj.organizacion_id, c.cliente_id, c.deudor_id, nullif(trim(gj.numero_rol), ''),
               (SELECT t.id FROM tribunales t
                WHERE lower(t.nombre) = lower(trim(gj.tribunal))
                  AND (t.organizacion_id IS NULL OR t.organizacion_id = gj.organizacion_id)
                ORDER BY t.organizacion_id NULLS FIRST LIMIT 1),
               COALESCE(gj.fecha_ingreso, c.fecha_traspaso, c.fecha_ingreso),
               gj.abogado_id,
               concat_ws(E'\\n', nullif(gj.estado_proceso, ''), nullif(gj.observaciones, '')),
               COALESCE(gj.abogado_id, c.ejecutivo_id,
                        (SELECT u.id FROM usuarios u WHERE u.organizacion_id = gj.organizacion_id
                         ORDER BY u.created_at LIMIT 1)),
               COALESCE(gj.created_at, NOW()), COALESCE(gj.updated_at, NOW())
        FROM gestiones_judiciales gj
        JOIN cobranzas c ON c.id = gj.cobranza_id
    """)
    op.execute("""
        INSERT INTO causa_cobranzas (organizacion_id, causa_id, cobranza_id)
        SELECT organizacion_id, id, cobranza_id FROM gestiones_judiciales
    """)
    op.execute(f"REVOKE INSERT, UPDATE ON gestiones_judiciales FROM {ROL_APP}")


def downgrade() -> None:
    raise NotImplementedError("Restaurar respaldo para volver atrás.")

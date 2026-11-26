"""Lo necesario para operar con la cartera real de un cliente.

  - Estado 'eliminada' (eliminada de cartera): el cliente indica que la
    cobranza ya no corresponde. Queda en la base y en los informes como tal.
  - ID cliente único por FILIAL (no por cliente): un mismo cliente puede
    numerar las cuentas de cada filial por separado y repetir IDs. Una
    cobranza sin filial cuenta como su propia "filial" (NULLS NOT DISTINCT).
  - Anulación de pagos: un pago mal ingresado se anula (una sola vez, con
    motivo y quién); no se borra ni se edita, y su gestión original queda.
    La base sigue impidiendo cualquier otro cambio a un pago.
  - Recordatorios con tipo (llamada, WhatsApp, correo, visita, tarea) para
    ordenar la agenda por secciones.
  - `trabajos`: cargas masivas grandes que corren en segundo plano, con su
    avance y resultado.
  - Tipos de gestión de sistema para pago anulado, eliminada de cartera y
    acuerdo dado de baja.

Revisión: 0015
"""

from alembic import op
from sqlalchemy import text

from migraciones.utilidades import ROL_APP, proteger_tabla_tenant

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

TIPOS = [
    ("Pago anulado", "pago_anulado", "pago"),
    ("Eliminada de cartera", "eliminada_cartera", "otro"),
    ("Acuerdo dado de baja", "acuerdo_baja", "negativo"),
]


def upgrade() -> None:
    conn = op.get_bind()

    # ------------------------------------------------ estado 'eliminada'
    op.execute("""
        DO $$
        DECLARE r RECORD;
        BEGIN
            FOR r IN SELECT conname FROM pg_constraint
                     WHERE conrelid = 'public.cobranzas'::regclass AND contype = 'c'
                       AND pg_get_constraintdef(oid) LIKE '%castigo%'
            LOOP
                EXECUTE format('ALTER TABLE public.cobranzas DROP CONSTRAINT %I', r.conname);
            END LOOP;
        END $$
    """)
    op.execute("""
        ALTER TABLE cobranzas ADD CONSTRAINT ck_cobranzas_estado CHECK (estado IN (
            'activa', 'acuerdo_pago', 'judicial', 'pagada', 'archivada', 'castigo', 'eliminada'))
    """)

    # ------------------------------------------------ ID cliente por filial
    op.execute("ALTER TABLE cobranzas DROP CONSTRAINT IF EXISTS uq_cobranza_id_externo")
    op.execute("""
        CREATE UNIQUE INDEX uq_cobranza_id_externo
            ON cobranzas (cliente_id, filial_id, id_externo) NULLS NOT DISTINCT
            WHERE id_externo IS NOT NULL
    """)

    # ------------------------------------------------ anulación de pagos
    op.execute("""
        ALTER TABLE pagos
            ADD COLUMN anulado_at       TIMESTAMPTZ,
            ADD COLUMN anulado_por      UUID,
            ADD COLUMN motivo_anulacion TEXT,
            ADD CONSTRAINT fk_pagos_anulado_por FOREIGN KEY (organizacion_id, anulado_por)
                REFERENCES usuarios (organizacion_id, id),
            ADD CONSTRAINT ck_pagos_anulacion CHECK (
                (anulado_at IS NULL AND anulado_por IS NULL AND motivo_anulacion IS NULL)
                OR (anulado_at IS NOT NULL AND anulado_por IS NOT NULL
                    AND length(trim(motivo_anulacion)) >= 3))
    """)
    op.execute("""
        CREATE FUNCTION pagos_solo_anulacion() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            -- Lo único que se permite: anular un pago vigente, una vez.
            IF TG_OP = 'UPDATE' AND OLD.anulado_at IS NULL AND NEW.anulado_at IS NOT NULL
               AND (to_jsonb(NEW) - 'anulado_at' - 'anulado_por' - 'motivo_anulacion')
                 = (to_jsonb(OLD) - 'anulado_at' - 'anulado_por' - 'motivo_anulacion') THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'Los pagos son inmutables: un pago mal ingresado se anula, no se edita ni se borra'
                USING ERRCODE = 'insufficient_privilege';
        END $$
    """)
    op.execute("DROP TRIGGER IF EXISTS trg_pagos_inmutable ON pagos")
    op.execute("""
        CREATE TRIGGER trg_pagos_inmutable BEFORE UPDATE OR DELETE ON pagos
            FOR EACH ROW EXECUTE FUNCTION pagos_solo_anulacion()
    """)
    op.execute(f"GRANT UPDATE (anulado_at, anulado_por, motivo_anulacion) ON pagos TO {ROL_APP}")
    op.execute("CREATE INDEX idx_pagos_vigentes ON pagos (organizacion_id, fecha_pago) WHERE anulado_at IS NULL")

    # Los informes de recupero y rendición no cuentan los pagos anulados.
    op.execute("""
        CREATE OR REPLACE VIEW vista_recupero WITH (security_invoker = true) AS
        SELECT
            p.organizacion_id,
            p.id                                    AS pago_id,
            p.fecha_pago,
            date_trunc('month', p.fecha_pago)::date AS mes,
            c.numero                                AS numero_cobranza,
            c.id_externo,
            c.cliente_id,
            cl.razon_social                         AS cliente,
            f.nombre                                AS filial,
            d.nombre                                AS deudor,
            d.rut                                   AS rut_deudor,
            p.monto                                 AS total_recibido,
            p.capital,
            p.honorarios,
            p.intereses,
            p.gastos_judiciales,
            p.estado_pago,
            p.descripcion_estado,
            p.forma_pago,
            p.numero_comprobante,
            cu.numero_cuota,
            ap.numero_cuotas                        AS total_cuotas_acuerdo,
            u.nombre                                AS registrado_por
        FROM pagos p
        JOIN cobranzas c    ON c.id = p.cobranza_id
        JOIN clientes cl    ON cl.id = c.cliente_id
        JOIN deudores d     ON d.id = c.deudor_id
        JOIN usuarios u     ON u.id = p.usuario_id
        LEFT JOIN filiales f         ON f.id = c.filial_id
        LEFT JOIN cuotas cu          ON cu.id = p.cuota_id
        LEFT JOIN acuerdos_pago ap   ON ap.id = cu.acuerdo_id
        WHERE p.anulado_at IS NULL
    """)
    op.execute("""
        CREATE OR REPLACE VIEW vista_rendicion WITH (security_invoker = true) AS
        SELECT
            p.organizacion_id,
            date_trunc('month', p.fecha_pago)::date  AS mes,
            c.cliente_id,
            cl.razon_social                           AS cliente,
            f.nombre                                  AS filial,
            count(p.id)                               AS cantidad_pagos,
            sum(p.capital)                            AS total_capital,
            sum(p.honorarios)                         AS total_honorarios,
            sum(p.intereses)                          AS total_intereses,
            sum(p.capital + p.intereses)              AS total_a_rendir_cliente,
            sum(p.monto)                              AS total_recibido
        FROM pagos p
        JOIN cobranzas c  ON c.id = p.cobranza_id
        JOIN clientes cl  ON cl.id = c.cliente_id
        LEFT JOIN filiales f ON f.id = c.filial_id
        WHERE p.anulado_at IS NULL
        GROUP BY p.organizacion_id, date_trunc('month', p.fecha_pago),
                 c.cliente_id, cl.razon_social, f.nombre
    """)

    # ------------------------------------------------ recordatorios por tipo
    op.execute("""
        ALTER TABLE recordatorios ADD COLUMN tipo VARCHAR(20) NOT NULL DEFAULT 'tarea'
            CHECK (tipo IN ('llamada', 'whatsapp', 'correo', 'visita', 'tarea'))
    """)

    # ------------------------------------------------ trabajos en segundo plano
    op.execute("""
        CREATE TABLE trabajos (
            id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            organizacion_id UUID         NOT NULL REFERENCES organizaciones(id),
            tipo            VARCHAR(40)  NOT NULL,
            estado          VARCHAR(20)  NOT NULL DEFAULT 'en_cola'
                                CHECK (estado IN ('en_cola', 'procesando', 'terminado', 'error')),
            archivo         VARCHAR(255),
            total           INTEGER      NOT NULL DEFAULT 0,
            procesadas      INTEGER      NOT NULL DEFAULT 0,
            resultado       JSONB,
            creado_por      UUID         NOT NULL,
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            terminado_at    TIMESTAMPTZ,
            CONSTRAINT fk_trabajos_creador FOREIGN KEY (organizacion_id, creado_por)
                REFERENCES usuarios (organizacion_id, id)
        )
    """)
    op.execute("CREATE INDEX idx_trabajos_org ON trabajos (organizacion_id, created_at DESC)")
    proteger_tabla_tenant("trabajos")

    # ------------------------------------------------ tipos de gestión nuevos
    for nombre, codigo, categoria in TIPOS:
        conn.execute(text("""
            INSERT INTO tipos_gestion (nombre, codigo, categoria)
            SELECT :n, :c, :cat
            WHERE NOT EXISTS (SELECT 1 FROM tipos_gestion
                              WHERE organizacion_id IS NULL AND (codigo = :c OR nombre = :n))
        """), {"n": nombre, "c": codigo, "cat": categoria})
    # Estos registros no son "la primera gestión": no sacan a la cobranza de ingreso.
    op.execute("""
        CREATE OR REPLACE FUNCTION gestion_inicia_extrajudicial() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF EXISTS (SELECT 1 FROM cobranzas WHERE id = NEW.cobranza_id AND etapa = 'ingreso')
               AND NOT EXISTS (SELECT 1 FROM tipos_gestion t
                               WHERE t.id = NEW.tipo_id
                                 AND t.codigo IN ('cambio_datos', 'etapa', 'eliminada_cartera',
                                                  'pago_anulado', 'acuerdo_baja')) THEN
                PERFORM set_config('app.usuario_id', NEW.usuario_id::text, true);
                PERFORM set_config('app.motivo_etapa', 'Primera gestión registrada', true);
                UPDATE cobranzas SET etapa = 'extrajudicial'
                    WHERE id = NEW.cobranza_id AND etapa = 'ingreso';
                PERFORM set_config('app.motivo_etapa', '', true);
            END IF;
            RETURN NEW;
        END $$
    """)


def downgrade() -> None:
    raise NotImplementedError("Restaurar respaldo para volver atrás.")

"""Generalización: el modelo deja de ser "de clínicas" y sirve a cualquier cartera.

  - `pacientes` pasa a `terceros`: personas relacionadas con la deuda que no
    son el deudor (paciente, aval, codeudor, beneficiario...). Una cobranza
    puede tener varios, cada uno con su rol (tabla `cobranza_terceros`).
  - Columnas con nombre de rubro pasan a nombres neutros:
        numero_liquidacion        → numero_operacion
        fecha_atencion            → fecha_origen
        numero_pagare             → numero_documento
        fecha_ejecucion_pagare    → fecha_emision_documento
        fecha_vencimiento_pagare  → fecha_vencimiento_documento
        deudores.en_dicom         → en_boletin_comercial
  - Lo que es propio de un rubro (previsión de salud, fecha de alta) sale del
    núcleo y pasa a CAMPOS PERSONALIZADOS: cada estudio define sus propios
    campos (por organización o solo para un mandante) y se guardan en
    `datos_extra` (JSONB). Los datos existentes se migran ahí sin perderse.
  - `tipos_gestion` gana un `codigo` estable (el código usa el código, no el
    nombre, que cada estudio puede traducir) y una categoría para la agenda.

Revisión: 0003
"""

from alembic import op
from sqlalchemy import text

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

RENOMBRES_COBRANZA = [
    ("numero_liquidacion", "numero_operacion"),
    ("fecha_atencion", "fecha_origen"),
    ("numero_pagare", "numero_documento"),
    ("fecha_ejecucion_pagare", "fecha_emision_documento"),
    ("fecha_vencimiento_pagare", "fecha_vencimiento_documento"),
]

# (nombre actual, código, categoría)
TIPOS_SISTEMA = [
    ("Llamada telefónica", "llamada", "contacto"),
    ("Email enviado", "email", "contacto"),
    ("WhatsApp", "whatsapp", "contacto"),
    ("Carta de cobranza", "carta", "contacto"),
    ("Acuerdo de pago", "acuerdo", "pago"),
    ("Visita en terreno", "visita", "contacto"),
    ("Nota interna", "nota", "otro"),
    ("Gestión automática", "automatica", "otro"),
    ("Cobranza ingresada al sistema", "ingreso", "otro"),
    ("Demanda presentada", "demanda", "judicial"),
    ("Pagaré ejecutado", "documento_ejecutado", "judicial"),
    ("Acuerdo incumplido", "acuerdo_incumplido", "negativo"),
    ("Abono", "abono", "pago"),
    ("Pagado", "pagado", "pago"),
]
TIPOS_NUEVOS = [
    ("No contesta", "no_contesta", "contacto"),
    ("Promesa de pago", "promesa_pago", "pago"),
    ("Negativa de pago", "negativa_pago", "negativo"),
    ("SMS enviado", "sms", "contacto"),
]


def upgrade() -> None:
    conn = op.get_bind()

    # ------------------------------------------------ campos personalizados
    op.execute("""
        CREATE TABLE campos_personalizados (
            id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            organizacion_id UUID         NOT NULL REFERENCES organizaciones(id),
            entidad         VARCHAR(20)  NOT NULL CHECK (entidad IN ('cobranza', 'deudor')),
            -- Clave dentro de datos_extra: minúsculas, números y guion bajo.
            clave           VARCHAR(50)  NOT NULL CHECK (clave ~ '^[a-z][a-z0-9_]*$'),
            etiqueta        VARCHAR(100) NOT NULL,
            tipo            VARCHAR(20)  NOT NULL DEFAULT 'texto'
                                CHECK (tipo IN ('texto', 'numero', 'monto', 'fecha',
                                                'seleccion', 'si_no')),
            opciones        JSONB        NOT NULL DEFAULT '[]'::jsonb,  -- para 'seleccion'
            -- NULL = aplica a todas las cobranzas; con valor = solo a las de
            -- ese mandante (ej. "Previsión" solo para la clínica).
            cliente_id      UUID,
            obligatorio     BOOLEAN      NOT NULL DEFAULT FALSE,
            orden           INTEGER      NOT NULL DEFAULT 0,
            activo          BOOLEAN      NOT NULL DEFAULT TRUE,
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_campo_clave UNIQUE (organizacion_id, entidad, clave),
            CONSTRAINT fk_campos_cliente FOREIGN KEY (organizacion_id, cliente_id)
                REFERENCES clientes (organizacion_id, id)
        )
    """)
    op.execute("ALTER TABLE cobranzas ADD COLUMN datos_extra JSONB NOT NULL DEFAULT '{}'::jsonb")
    op.execute("ALTER TABLE deudores ADD COLUMN datos_extra JSONB NOT NULL DEFAULT '{}'::jsonb")

    # Previsión y fecha de alta (propias de salud) → campos personalizados,
    # solo en las organizaciones que los usaban.
    op.execute("""
        INSERT INTO campos_personalizados (organizacion_id, entidad, clave, etiqueta, tipo, orden)
        SELECT DISTINCT organizacion_id, 'cobranza', 'prevision', 'Previsión', 'texto', 10
        FROM cobranzas WHERE prevision IS NOT NULL AND prevision <> ''
    """)
    op.execute("""
        INSERT INTO campos_personalizados (organizacion_id, entidad, clave, etiqueta, tipo, orden)
        SELECT DISTINCT organizacion_id, 'cobranza', 'fecha_alta', 'Fecha de alta', 'fecha', 20
        FROM cobranzas WHERE fecha_alta IS NOT NULL
    """)
    op.execute("""
        UPDATE cobranzas SET datos_extra = jsonb_strip_nulls(jsonb_build_object(
            'prevision', NULLIF(prevision, ''),
            'fecha_alta', to_char(fecha_alta, 'YYYY-MM-DD')
        ))
        WHERE (prevision IS NOT NULL AND prevision <> '') OR fecha_alta IS NOT NULL
    """)
    op.execute("ALTER TABLE cobranzas DROP COLUMN prevision, DROP COLUMN fecha_alta")

    # ------------------------------------------------ renombres neutros
    for viejo, nuevo in RENOMBRES_COBRANZA:
        op.execute(f"ALTER TABLE cobranzas RENAME COLUMN {viejo} TO {nuevo}")
    op.execute("ALTER TABLE deudores RENAME COLUMN en_dicom TO en_boletin_comercial")

    op.execute("ALTER TABLE cobranzas DROP CONSTRAINT IF EXISTS cobranzas_tipo_documento_check")
    op.execute("""
        ALTER TABLE cobranzas ADD CONSTRAINT cobranzas_tipo_documento_check
            CHECK (tipo_documento IN ('pagare', 'factura', 'letra', 'cheque',
                                      'contrato', 'boleta', 'credito', 'otro'))
    """)

    # ------------------------------------------------ pacientes → terceros
    op.execute("ALTER TABLE pacientes RENAME TO terceros")
    op.execute("ALTER TABLE terceros ALTER COLUMN rut DROP NOT NULL")
    op.execute("ALTER TABLE terceros RENAME CONSTRAINT uq_pacientes_rut TO uq_terceros_rut")
    op.execute("ALTER TABLE terceros RENAME CONSTRAINT uq_pacientes_org_id TO uq_terceros_org_id")
    op.execute("ALTER TABLE terceros RENAME CONSTRAINT fk_pacientes_organizacion TO fk_terceros_organizacion")
    op.execute("ALTER INDEX idx_pacientes_organizacion RENAME TO idx_terceros_organizacion")
    op.execute("ALTER TABLE contactos_paciente RENAME TO contactos_tercero")
    op.execute("ALTER TABLE contactos_tercero RENAME COLUMN paciente_id TO tercero_id")
    op.execute("ALTER TABLE contactos_tercero RENAME CONSTRAINT fk_contactos_paciente_paciente_id TO fk_contactos_tercero_tercero_id")
    op.execute("ALTER TABLE contactos_tercero RENAME CONSTRAINT fk_contactos_paciente_organizacion TO fk_contactos_tercero_organizacion")
    op.execute("ALTER INDEX idx_contactos_paciente_organizacion RENAME TO idx_contactos_tercero_organizacion")

    op.execute("""
        CREATE TABLE cobranza_terceros (
            organizacion_id UUID        NOT NULL REFERENCES organizaciones(id),
            cobranza_id     UUID        NOT NULL,
            tercero_id      UUID        NOT NULL,
            rol             VARCHAR(30) NOT NULL
                                CHECK (rol IN ('paciente', 'aval', 'codeudor', 'beneficiario',
                                               'representante_legal', 'otro')),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (cobranza_id, tercero_id, rol),
            CONSTRAINT fk_cobranza_terceros_cobranza FOREIGN KEY (organizacion_id, cobranza_id)
                REFERENCES cobranzas (organizacion_id, id),
            CONSTRAINT fk_cobranza_terceros_tercero FOREIGN KEY (organizacion_id, tercero_id)
                REFERENCES terceros (organizacion_id, id)
        )
    """)
    op.execute("CREATE INDEX idx_cobranza_terceros_org ON cobranza_terceros(organizacion_id)")
    op.execute("CREATE INDEX idx_cobranza_terceros_tercero ON cobranza_terceros(tercero_id)")
    op.execute("""
        INSERT INTO cobranza_terceros (organizacion_id, cobranza_id, tercero_id, rol)
        SELECT organizacion_id, id, paciente_id, 'paciente'
        FROM cobranzas WHERE paciente_id IS NOT NULL
    """)
    op.execute("DROP INDEX IF EXISTS idx_cobranzas_paciente")
    op.execute("ALTER TABLE cobranzas DROP COLUMN paciente_id")

    # ------------------------------------------------ tipos de gestión
    op.execute("""
        ALTER TABLE tipos_gestion
            ADD COLUMN codigo    VARCHAR(40),
            ADD COLUMN categoria VARCHAR(20) NOT NULL DEFAULT 'otro'
                CHECK (categoria IN ('contacto', 'pago', 'negativo', 'judicial', 'otro'))
    """)
    for nombre, codigo, categoria in TIPOS_SISTEMA:
        conn.execute(
            text("UPDATE tipos_gestion SET codigo = :c, categoria = :cat "
                 "WHERE organizacion_id IS NULL AND nombre = :n"),
            {"c": codigo, "cat": categoria, "n": nombre},
        )
    for nombre, codigo, categoria in TIPOS_NUEVOS:
        conn.execute(
            text("INSERT INTO tipos_gestion (nombre, codigo, categoria) VALUES (:n, :c, :cat)"),
            {"c": codigo, "cat": categoria, "n": nombre},
        )
    # Código único entre los tipos de sistema (los propios de cada estudio no
    # llevan código).
    op.execute("""
        CREATE UNIQUE INDEX uq_tipos_gestion_codigo ON tipos_gestion(codigo)
            WHERE codigo IS NOT NULL AND organizacion_id IS NULL
    """)

    # ------------------------------------------------ vistas
    # Todas exponen organizacion_id y corren con los permisos de quien
    # consulta (security_invoker): la RLS de las tablas se aplica también
    # a través de la vista.
    for vista in ("vista_recupero", "vista_rendicion", "vista_acuerdos_estado",
                  "vista_deudor_cobranzas"):
        op.execute(f"DROP VIEW IF EXISTS {vista}")

    op.execute("""
        CREATE VIEW vista_recupero WITH (security_invoker = true) AS
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
    """)
    op.execute("""
        CREATE VIEW vista_rendicion WITH (security_invoker = true) AS
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
        GROUP BY p.organizacion_id, date_trunc('month', p.fecha_pago),
                 c.cliente_id, cl.razon_social, f.nombre
    """)
    op.execute("""
        CREATE VIEW vista_acuerdos_estado WITH (security_invoker = true) AS
        SELECT
            ap.organizacion_id,
            ap.id                                    AS acuerdo_id,
            c.numero                                 AS numero_cobranza,
            c.id_externo,
            cl.razon_social                          AS cliente,
            f.nombre                                 AS filial,
            d.nombre                                 AS deudor,
            d.rut,
            ap.pie,
            ap.monto_total_acordado,
            ap.numero_cuotas,
            ap.dia_pago,
            ap.fecha_acuerdo,
            ap.fecha_termino,
            ap.firma_cliente,
            ap.estado,
            count(cu.id) FILTER (WHERE cu.estado = 'pagada')                AS cuotas_pagadas,
            count(cu.id) FILTER (WHERE cu.estado IN ('pendiente', 'pagada_parcial', 'vencida'))
                                                                           AS cuotas_pendientes,
            count(cu.id) FILTER (WHERE cu.estado = 'vencida')               AS meses_atraso
        FROM acuerdos_pago ap
        JOIN cobranzas c  ON c.id = ap.cobranza_id
        JOIN clientes cl  ON cl.id = c.cliente_id
        JOIN deudores d   ON d.id = c.deudor_id
        LEFT JOIN filiales f ON f.id = c.filial_id
        LEFT JOIN cuotas cu  ON cu.acuerdo_id = ap.id
        WHERE ap.estado = 'vigente'
        GROUP BY ap.organizacion_id, ap.id, c.numero, c.id_externo,
                 cl.razon_social, f.nombre, d.nombre, d.rut
    """)
    op.execute("""
        CREATE VIEW vista_deudor_cobranzas WITH (security_invoker = true) AS
        SELECT
            d.organizacion_id,
            d.id                                     AS deudor_id,
            d.rut,
            d.nombre                                 AS deudor,
            count(c.id)                              AS total_cobranzas,
            count(c.id) FILTER (WHERE c.estado = 'activa')        AS cobranzas_activas,
            count(c.id) FILTER (WHERE c.estado = 'acuerdo_pago')  AS en_acuerdo,
            count(c.id) FILTER (WHERE c.estado = 'pagada')        AS pagadas,
            count(c.id) FILTER (WHERE c.estado = 'judicial')      AS judiciales,
            sum(c.monto_original)                    AS total_deuda_original,
            sum(c.monto_actual)                      AS total_deuda_actual
        FROM deudores d
        LEFT JOIN cobranzas c ON c.deudor_id = d.id
        GROUP BY d.organizacion_id, d.id, d.rut, d.nombre
    """)


def downgrade() -> None:
    raise NotImplementedError("Restaurar respaldo para volver atrás.")

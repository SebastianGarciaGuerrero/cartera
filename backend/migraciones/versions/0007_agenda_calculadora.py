"""Fase 2: agenda, recordatorios, UF del día, acuerdos asistidos y mensaje de pago.

  - `recordatorios`: tareas que cada persona se anota (llamar a tal deudor el
    jueves, revisar un pago). No se borran: se marcan hechas o descartadas.
  - `indicadores`: UF (y a futuro UTM, IPC) por fecha. Es dato público y
    común a todas las organizaciones; lo escribe solo el sistema.
  - `cuotas` guarda su desglose (capital, interés, honorarios, gastos,
    comisión): al pagar una cuota calculada con la calculadora 3-6-9, el
    abono se desglosa solo y la rendición al mandante sale exacta.
  - `clientes.instrucciones_pago`: datos de transferencia propios de un
    mandante (cuando el deudor le paga directo a él). Si no hay, se usan los
    del estudio.

Revisión: 0007
"""

from alembic import op

from migraciones.utilidades import ROL_APP, proteger_tabla_tenant

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE recordatorios (
            id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            organizacion_id UUID         NOT NULL REFERENCES organizaciones(id),
            usuario_id      UUID         NOT NULL,          -- a quién le toca
            cobranza_id     UUID,                           -- opcional
            fecha           DATE         NOT NULL,
            hora            TIME,
            titulo          VARCHAR(200) NOT NULL,
            nota            TEXT,
            estado          VARCHAR(20)  NOT NULL DEFAULT 'pendiente'
                                CHECK (estado IN ('pendiente', 'hecho', 'descartado')),
            completado_at   TIMESTAMPTZ,
            creado_por      UUID         NOT NULL,
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            CONSTRAINT fk_recordatorios_usuario FOREIGN KEY (organizacion_id, usuario_id)
                REFERENCES usuarios (organizacion_id, id),
            CONSTRAINT fk_recordatorios_creador FOREIGN KEY (organizacion_id, creado_por)
                REFERENCES usuarios (organizacion_id, id),
            CONSTRAINT fk_recordatorios_cobranza FOREIGN KEY (organizacion_id, cobranza_id)
                REFERENCES cobranzas (organizacion_id, id)
        )
    """)
    op.execute("""
        CREATE INDEX idx_recordatorios_agenda ON recordatorios (organizacion_id, usuario_id, fecha)
            WHERE estado = 'pendiente'
    """)
    op.execute("CREATE INDEX idx_recordatorios_cobranza ON recordatorios (cobranza_id)")
    proteger_tabla_tenant("recordatorios")

    op.execute("""
        CREATE TABLE indicadores (
            codigo     VARCHAR(20)   NOT NULL,      -- 'uf'
            fecha      DATE          NOT NULL,
            valor      NUMERIC(14,4) NOT NULL CHECK (valor > 0),
            fuente     VARCHAR(50),
            created_at TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
            PRIMARY KEY (codigo, fecha)
        )
    """)
    op.execute("ALTER TABLE indicadores ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY lectura_indicadores ON indicadores TO {ROL_APP} USING (true)")
    op.execute(f"GRANT SELECT ON indicadores TO {ROL_APP}")

    op.execute("""
        ALTER TABLE cuotas
            ADD COLUMN capital           NUMERIC(15,2),
            ADD COLUMN intereses         NUMERIC(15,2),
            ADD COLUMN honorarios        NUMERIC(15,2),
            ADD COLUMN gastos_judiciales NUMERIC(15,2),
            ADD COLUMN comision          NUMERIC(15,2)
    """)
    op.execute("ALTER TABLE clientes ADD COLUMN instrucciones_pago TEXT")

    # Agenda: cuotas abiertas por fecha de vencimiento.
    op.execute("""
        CREATE INDEX idx_cuotas_abiertas_org ON cuotas (organizacion_id, fecha_vencimiento)
            WHERE estado IN ('pendiente', 'pagada_parcial', 'vencida')
    """)
    op.execute("""
        CREATE INDEX idx_gestiones_org_cobranza_fecha
            ON gestiones (organizacion_id, cobranza_id, fecha_gestion DESC)
    """)


def downgrade() -> None:
    raise NotImplementedError("Restaurar respaldo para volver atrás.")

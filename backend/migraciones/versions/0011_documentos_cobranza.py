"""Varios documentos por cobranza.

Una cobranza puede respaldarse en varios documentos (cheques, facturas,
letras, pagarés…), cada uno con su número, vencimiento, monto, banco,
plaza y protesto. De ahí sale la prescripción de cada uno. Los campos de
documento de `cobranzas` quedan como el documento principal (compatibilidad).

  - `documentos_cobranza`: los documentos. Se editan; quitar uno es
    marcarlo inactivo (nunca DELETE).
  - La cartera existente recibe su documento principal.
  - Índice para la agenda: compromisos por fecha de próximo contacto.
  - Trigger: toda cobranza nueva (pantalla, carga masiva) recibe su
    documento principal. Una migración de datos que cargue los documentos
    por su cuenta lo apaga con set_config('app.sin_documento_principal', '1').

Revisión: 0011
"""

from alembic import op

from migraciones.utilidades import ROL_APP, proteger_tabla_tenant

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE documentos_cobranza (
            id                UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
            organizacion_id   UUID          NOT NULL REFERENCES organizaciones(id),
            cobranza_id       UUID          NOT NULL,
            tipo              VARCHAR(20)   NOT NULL DEFAULT 'pagare'
                CHECK (tipo IN ('pagare', 'factura', 'letra', 'cheque', 'contrato', 'boleta', 'credito', 'otro')),
            numero            VARCHAR(50),
            fecha_emision     DATE,
            fecha_vencimiento DATE,
            monto             NUMERIC(15,2) CHECK (monto >= 0),
            banco             VARCHAR(80),
            plaza             VARCHAR(80),
            causal_protesto   VARCHAR(80),
            fecha_protesto    DATE,
            observaciones     TEXT,
            activo            BOOLEAN       NOT NULL DEFAULT TRUE,
            creado_por        UUID,
            created_at        TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
            CONSTRAINT fk_documentos_cobranza FOREIGN KEY (organizacion_id, cobranza_id)
                REFERENCES cobranzas (organizacion_id, id),
            CONSTRAINT fk_documentos_creador FOREIGN KEY (organizacion_id, creado_por)
                REFERENCES usuarios (organizacion_id, id)
        )
    """)
    op.execute("CREATE INDEX idx_documentos_cobranza ON documentos_cobranza (cobranza_id) WHERE activo")
    proteger_tabla_tenant("documentos_cobranza")

    # Cartera existente: su documento principal.
    op.execute("""
        INSERT INTO documentos_cobranza (organizacion_id, cobranza_id, tipo, numero, fecha_emision,
                                         fecha_vencimiento, monto, created_at)
        SELECT organizacion_id, id, COALESCE(tipo_documento, 'otro'), numero_documento, fecha_emision_documento,
               fecha_vencimiento_documento, monto_original, COALESCE(created_at, NOW())
        FROM cobranzas
    """)

    op.execute("""
        CREATE FUNCTION cobranza_documento_principal() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF COALESCE(current_setting('app.sin_documento_principal', true), '') = '1' THEN
                RETURN NEW;
            END IF;
            INSERT INTO documentos_cobranza (organizacion_id, cobranza_id, tipo, numero, fecha_emision,
                                             fecha_vencimiento, monto)
            VALUES (NEW.organizacion_id, NEW.id, COALESCE(NEW.tipo_documento, 'otro'), NEW.numero_documento,
                    NEW.fecha_emision_documento, NEW.fecha_vencimiento_documento, NEW.monto_original);
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER trg_cobranzas_documento_principal AFTER INSERT ON cobranzas
            FOR EACH ROW EXECUTE FUNCTION cobranza_documento_principal()
    """)
    op.execute(f"GRANT EXECUTE ON FUNCTION cobranza_documento_principal() TO {ROL_APP}")

    # Agenda: los compromisos se buscan por fecha (no recorriendo la cartera).
    op.execute("""
        CREATE INDEX idx_gestiones_proximo_contacto ON gestiones (organizacion_id, fecha_proximo_contacto)
            WHERE fecha_proximo_contacto IS NOT NULL
    """)


def downgrade() -> None:
    raise NotImplementedError("Restaurar respaldo para volver atrás.")

"""Tipos de gestión para los cambios que se registran solos.

Todo cambio sobre un caso queda en el historial como gestión de quien lo
hizo: gastos, trámites, embargos, cambios de etapa y de datos (cobranza,
documentos, deudor y sus contactos, estado del acuerdo).

Esos registros no son una gestión de cobranza: no sacan a la cobranza de
"ingreso" (la primera gestión de verdad la pasa a extrajudicial).

Revisión: 0014
"""

from alembic import op
from sqlalchemy import text

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

TIPOS = [
    ("Gasto judicial", "gasto", "judicial"),
    ("Trámite judicial", "tramite", "judicial"),
    ("Embargo", "embargo", "judicial"),
    ("Cambio de etapa", "etapa", "otro"),
    ("Cambio de datos", "cambio_datos", "otro"),
]


def upgrade() -> None:
    conn = op.get_bind()
    for nombre, codigo, categoria in TIPOS:
        conn.execute(text("""
            INSERT INTO tipos_gestion (nombre, codigo, categoria)
            SELECT :n, :c, :cat
            WHERE NOT EXISTS (SELECT 1 FROM tipos_gestion
                              WHERE organizacion_id IS NULL AND (codigo = :c OR nombre = :n))
        """), {"n": nombre, "c": codigo, "cat": categoria})
    op.execute("""
        CREATE OR REPLACE FUNCTION gestion_inicia_extrajudicial() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF EXISTS (SELECT 1 FROM cobranzas WHERE id = NEW.cobranza_id AND etapa = 'ingreso')
               AND NOT EXISTS (SELECT 1 FROM tipos_gestion t
                               WHERE t.id = NEW.tipo_id AND t.codigo IN ('cambio_datos', 'etapa')) THEN
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

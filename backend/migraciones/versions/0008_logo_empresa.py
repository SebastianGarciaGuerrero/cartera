"""Logo de cada organización (membrete de documentos y barra lateral).

Se guarda en la base (no en el disco del servidor): así viaja con los
respaldos y funciona igual con una o varias réplicas. Solo PNG o JPG de
hasta 1 MB (sin SVG: un SVG puede llevar scripts).

Revisión: 0008
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE empresa
            ADD COLUMN logo                BYTEA,
            ADD COLUMN logo_tipo           VARCHAR(30)
                CHECK (logo_tipo IN ('image/png', 'image/jpeg')),
            ADD COLUMN logo_actualizado_at TIMESTAMPTZ,
            ADD CONSTRAINT ck_empresa_logo_tamano CHECK (logo IS NULL OR octet_length(logo) <= 1048576)
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE empresa DROP COLUMN logo, DROP COLUMN logo_tipo, DROP COLUMN logo_actualizado_at")

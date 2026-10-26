"""% de honorarios judiciales por cliente.

Algunos clientes fijan el porcentaje de honorarios judiciales; con otros
el estudio lo decide en cada abono. `clientes.pct_honorarios_judicial`
vacío = libre (se usa el general del estudio y se puede cambiar).

Revisión: 0013
"""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE clientes ADD COLUMN pct_honorarios_judicial NUMERIC(5,2)
            CHECK (pct_honorarios_judicial >= 0 AND pct_honorarios_judicial <= 100)
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE clientes DROP COLUMN pct_honorarios_judicial")

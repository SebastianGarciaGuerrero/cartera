"""Fechas por defecto en hora de Chile.

`CURRENT_DATE` usa la zona de la base (UTC en Supabase): desde las 21:00
(o 20:00 en invierno) de Chile ya es "mañana". Una cobranza ingresada, un
acuerdo o un pago registrados de noche quedaban con la fecha del día
siguiente. Los tres defaults pasan a `fecha_chile()` (migración 0010).

Revisión: 0012
"""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE cobranzas ALTER COLUMN fecha_ingreso SET DEFAULT fecha_chile()")
    op.execute("ALTER TABLE acuerdos_pago ALTER COLUMN fecha_acuerdo SET DEFAULT fecha_chile()")
    op.execute("ALTER TABLE pagos ALTER COLUMN fecha_pago SET DEFAULT fecha_chile()")


def downgrade() -> None:
    op.execute("ALTER TABLE cobranzas ALTER COLUMN fecha_ingreso SET DEFAULT CURRENT_DATE")
    op.execute("ALTER TABLE acuerdos_pago ALTER COLUMN fecha_acuerdo SET DEFAULT CURRENT_DATE")
    op.execute("ALTER TABLE pagos ALTER COLUMN fecha_pago SET DEFAULT CURRENT_DATE")

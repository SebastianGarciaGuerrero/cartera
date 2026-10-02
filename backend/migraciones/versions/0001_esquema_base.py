"""Esquema base (lo que antes era database/init/001_schema.sql).

Funciona en dos situaciones:
  - Base VACÍA: crea las 17 tablas, índices y vistas originales.
  - Base EXISTENTE creada con el sistema anterior (Docker init o el script
    de Neon): no recrea nada; solo aplica el rebranding white-label si esa
    base todavía tiene los nombres de columna viejos. Así las bases que ya
    tienen datos entran a Alembic sin perder nada.

Revisión: 0001
"""

from migraciones.utilidades import ejecutar_sql_archivo, existe_tabla

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not existe_tabla("cobranzas"):
        ejecutar_sql_archivo("0001_esquema_base.sql")
    else:
        # Idempotente: renombra solo lo que falte y recrea vistas.
        ejecutar_sql_archivo("0001_whitelabel_legacy.sql")


def downgrade() -> None:
    raise NotImplementedError("La migración base no se revierte.")

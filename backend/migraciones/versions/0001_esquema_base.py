"""Esquema base.

Funciona en dos situaciones:
  - Base VACÍA: crea las tablas, índices y vistas originales.
  - Base EXISTENTE creada antes de usar Alembic: no recrea nada; solo se
    asegura de que exista la tabla `empresa`. Si la base todavía tiene los
    nombres de columna anteriores a la marca blanca (sin `id_externo`), se
    detiene con un mensaje: hay que actualizarla con la versión 3f4259e del
    repositorio antes de pasar a esta.

Revisión: 0001
"""

from migraciones.utilidades import ejecutar_sql_archivo, existe_columna, existe_tabla

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not existe_tabla("cobranzas"):
        ejecutar_sql_archivo("0001_esquema_base.sql")
        return
    if not existe_columna("cobranzas", "id_externo"):
        raise RuntimeError(
            "La base tiene nombres de columna de una versión antigua. Actualízala primero "
            "con la migración de marca blanca del commit 3f4259e y vuelve a correr Alembic."
        )
    ejecutar_sql_archivo("0001_adoptar_base_existente.sql")


def downgrade() -> None:
    raise NotImplementedError("La migración base no se revierte.")

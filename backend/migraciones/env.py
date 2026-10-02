"""
Entorno de Alembic: cómo se conecta a la base para correr migraciones.

Las migraciones de este proyecto se escriben a mano (SQL explícito), no con
autogenerate: el esquema tiene RLS, triggers, vistas y políticas que
autogenerate no ve. Por eso no se le pasa target_metadata.

Las migraciones corren con el usuario dueño de las tablas (el de
DATABASE_URL), nunca con el rol restringido de la aplicación.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool, text

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Número arbitrario y fijo: dos procesos que arrancan a la vez (dos réplicas
# del servidor) no pueden migrar en paralelo; el segundo espera al primero.
CANDADO_MIGRACIONES = 724_100_201


def _url() -> str:
    url = context.get_x_argument(as_dictionary=True).get("url")
    if url:
        return url
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    # Último recurso: la misma configuración que usa la app (lee backend/.env).
    from app.config import settings
    return settings.database_url


def run_migrations_offline() -> None:
    context.configure(url=_url(), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as conexion:
        conexion.execute(text("SELECT pg_advisory_lock(:k)"), {"k": CANDADO_MIGRACIONES})
        conexion.commit()
        try:
            context.configure(connection=conexion, transaction_per_migration=True)
            with context.begin_transaction():
                context.run_migrations()
        finally:
            conexion.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": CANDADO_MIGRACIONES})
            conexion.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

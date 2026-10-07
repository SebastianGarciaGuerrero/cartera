"""Supabase: el rol service_role (el de la "secret key") pierde acceso a las
tablas de Cartera.

Cartera no usa la API REST de Supabase: se conecta directo a PostgreSQL. La
secret key de Supabase entra como service_role, que se salta RLS; si esa
clave se filtra, daría acceso total a los datos de todos los estudios. Con
esto queda sin permisos sobre el esquema public (también para las tablas
que se creen después). El panel de Supabase sigue funcionando: usa otro rol.

En bases que no son Supabase (local, Neon) no hace nada.

Revisión: 0006
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
                REVOKE ALL ON ALL TABLES IN SCHEMA public FROM service_role;
                REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM service_role;
                REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM service_role;
                ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM service_role;
                ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM service_role;
                ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM service_role;
            END IF;
        END $$
    """)


def downgrade() -> None:
    pass

"""Row Level Security: el aislamiento entre organizaciones lo garantiza
PostgreSQL, no solo el código.

Modelo:
  - La app se conecta con el usuario dueño (el de DATABASE_URL), pero en cada
    transacción autenticada hace `SET LOCAL ROLE cartera_app` y fija
    `app.organizacion_id`. Ese rol NO es dueño de las tablas, así que las
    políticas RLS se le aplican: aunque el código olvidara un filtro, la base
    solo devuelve filas de la organización de la sesión.
  - cartera_app no tiene permiso DELETE en ninguna tabla (nunca se borra
    físico) ni UPDATE en gestiones, pagos ni bitácoras.
  - Sesiones y tokens no son visibles para cartera_app: solo el código de
    autenticación (que corre como dueño, antes de fijar la organización).
  - En Supabase: los roles anon/authenticated (los de la API REST pública)
    quedan sin ningún permiso sobre el esquema, y toda tabla tiene RLS
    activado, así que la clave pública no expone datos.

Revisión: 0005
"""

from alembic import op

from migraciones.utilidades import ROL_APP, proteger_tabla_tenant, bloquear_tabla_para_app

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

TENANT_EDITABLES = [
    "usuarios", "clientes", "filiales", "terceros", "contactos_tercero",
    "deudores", "contactos_deudor", "cobranzas", "cobranza_terceros",
    "acuerdos_pago", "cuotas", "gestiones_judiciales", "campos_personalizados",
    "empresa",
]
TENANT_SOLO_AGREGAR = ["gestiones", "pagos", "audit_log"]


def upgrade() -> None:
    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROL_APP}') THEN
                CREATE ROLE {ROL_APP} NOLOGIN NOINHERIT NOBYPASSRLS;
            END IF;
        END $$
    """)
    # El usuario de conexión necesita poder hacer SET ROLE cartera_app.
    op.execute(f"GRANT {ROL_APP} TO CURRENT_USER")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {ROL_APP}")

    for tabla in TENANT_EDITABLES:
        proteger_tabla_tenant(tabla)
    for tabla in TENANT_SOLO_AGREGAR:
        proteger_tabla_tenant(tabla, permisos="SELECT, INSERT")

    # Tipos de gestión: se ven los de sistema (organizacion_id NULL) y los
    # propios; solo se crean/editan los propios.
    proteger_tabla_tenant("tipos_gestion", lectura_global=True)

    # Accesos: el admin del estudio puede revisarlos; los escribe el código
    # de autenticación (como dueño).
    proteger_tabla_tenant("eventos_acceso", permisos="SELECT")

    # La organización solo se ve a sí misma, y solo puede cambiar su nombre y
    # su configuración (plan y estado los maneja la plataforma).
    op.execute("ALTER TABLE organizaciones ENABLE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY aislamiento_organizacion ON organizaciones TO {ROL_APP}
            USING (id = app_organizacion_actual())
            WITH CHECK (id = app_organizacion_actual())
    """)
    op.execute(f"GRANT SELECT ON organizaciones TO {ROL_APP}")
    op.execute(f"GRANT UPDATE (nombre, configuracion, updated_at) ON organizaciones TO {ROL_APP}")

    # Catálogo global de roles: lectura para todos.
    op.execute("ALTER TABLE roles ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY lectura_roles ON roles TO {ROL_APP} USING (true)")
    op.execute(f"GRANT SELECT ON roles TO {ROL_APP}")

    for tabla in ("sesiones", "tokens_un_uso", "alembic_version"):
        bloquear_tabla_para_app(tabla)

    for vista in ("vista_recupero", "vista_rendicion", "vista_acuerdos_estado",
                  "vista_deudor_cobranzas"):
        op.execute(f"GRANT SELECT ON {vista} TO {ROL_APP}")

    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {ROL_APP}")

    # Supabase expone el esquema public por REST a anon/authenticated.
    # Se les quita todo, también para las tablas que se creen en el futuro.
    op.execute("""
        DO $$
        DECLARE r TEXT;
        BEGIN
            FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                    EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA public FROM %I', r);
                    EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM %I', r);
                    EXECUTE format('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM %I', r);
                    EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM %I', r);
                    EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM %I', r);
                    EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM %I', r);
                END IF;
            END LOOP;
        END $$
    """)


def downgrade() -> None:
    raise NotImplementedError("Restaurar respaldo para volver atrás.")

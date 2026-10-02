"""Multi-organización (SaaS): cada estudio de cobranza es una organización.

Qué hace:
  1. Crea `organizaciones` (el tenant: plan, estado, correlativo propio).
  2. Agrega `organizacion_id` a todas las tablas de negocio.
  3. Si la base ya tenía datos (instalación de una sola empresa), los
     asigna a una organización "principal" creada con los datos de la
     tabla `empresa`. En una base nueva no crea ninguna organización:
     se dan de alta con el comando `python -m app.cli crear-organizacion`.
  4. `empresa` pasa de fila única a una fila por organización.
  5. Los UNIQUE de RUT pasan a ser por organización (dos estudios pueden
     cobrarle al mismo deudor sin chocar).
  6. Las FK se vuelven compuestas (organizacion_id, id): la base de datos
     rechaza que una cobranza apunte a un deudor de OTRA organización,
     aunque el código tuviera un error.
  7. El N° de cobranza pasa a ser correlativo por organización.
  8. Gestiones, pagos y audit_log quedan inmutables a nivel de base de
     datos (trigger): ni un UPDATE ni un DELETE pasan, venga de donde venga.

Revisión: 0002
"""

from alembic import op
from sqlalchemy import text

from migraciones.utilidades import soltar_fks_de_columna, soltar_unicos_de_columna

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# Tablas de negocio que pasan a pertenecer a una organización.
TABLAS_TENANT = [
    "usuarios", "clientes", "filiales", "pacientes", "contactos_paciente",
    "deudores", "contactos_deudor", "cobranzas", "gestiones", "acuerdos_pago",
    "cuotas", "pagos", "gestiones_judiciales",
]

# Tablas que otras referencian: necesitan UNIQUE (organizacion_id, id) para
# poder ser destino de una FK compuesta.
TABLAS_PADRE = [
    "usuarios", "clientes", "filiales", "pacientes", "deudores",
    "cobranzas", "acuerdos_pago", "cuotas",
]

# (tabla, columna, tabla destino, on delete)
FKS_COMPUESTAS = [
    ("filiales", "cliente_id", "clientes", None),
    ("contactos_paciente", "paciente_id", "pacientes", "CASCADE"),
    ("contactos_deudor", "deudor_id", "deudores", "CASCADE"),
    ("cobranzas", "cliente_id", "clientes", None),
    ("cobranzas", "filial_id", "filiales", None),
    ("cobranzas", "deudor_id", "deudores", None),
    ("cobranzas", "paciente_id", "pacientes", None),
    ("cobranzas", "ejecutivo_id", "usuarios", None),
    ("gestiones", "cobranza_id", "cobranzas", None),
    ("gestiones", "usuario_id", "usuarios", None),
    ("acuerdos_pago", "cobranza_id", "cobranzas", None),
    ("acuerdos_pago", "usuario_id", "usuarios", None),
    ("cuotas", "acuerdo_id", "acuerdos_pago", "CASCADE"),
    ("pagos", "cobranza_id", "cobranzas", None),
    ("pagos", "cuota_id", "cuotas", None),
    ("pagos", "usuario_id", "usuarios", None),
    ("gestiones_judiciales", "cobranza_id", "cobranzas", None),
    ("gestiones_judiciales", "abogado_id", "usuarios", None),
]


def _hay_datos() -> bool:
    conn = op.get_bind()
    for tabla in ("usuarios", "clientes", "deudores", "cobranzas"):
        if conn.execute(text(f"SELECT EXISTS (SELECT 1 FROM {tabla})")).scalar():
            return True
    return False


def upgrade() -> None:
    conn = op.get_bind()

    # ---------------------------------------------------------- 1. tenants
    op.execute("""
        CREATE TABLE organizaciones (
            id                        UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            nombre                    VARCHAR(200) NOT NULL,
            slug                      VARCHAR(60)  NOT NULL UNIQUE
                                          CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
            plan                      VARCHAR(20)  NOT NULL DEFAULT 'base'
                                          CHECK (plan IN ('base', 'profesional', 'premium')),
            estado                    VARCHAR(20)  NOT NULL DEFAULT 'activa'
                                          CHECK (estado IN ('prueba', 'activa', 'suspendida', 'cancelada')),
            prueba_hasta              DATE,
            -- Correlativo de N° de cobranza propio de cada organización.
            numero_cobranza_siguiente INTEGER      NOT NULL DEFAULT 1000
                                          CHECK (numero_cobranza_siguiente > 0),
            -- Ajustes que cada estudio maneja solo: etiquetas de la UI,
            -- funciones extra activadas, preferencias.
            configuracion             JSONB        NOT NULL DEFAULT '{}'::jsonb,
            created_at                TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at                TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
    """)

    # Organización "activa" de la transacción. La fija la app al inicio de
    # cada transacción autenticada (set_config(..., true) = solo dura la
    # transacción). NULL si no hay ninguna fijada.
    op.execute("""
        CREATE FUNCTION app_organizacion_actual() RETURNS UUID
        LANGUAGE sql STABLE
        AS $$ SELECT NULLIF(current_setting('app.organizacion_id', true), '')::uuid $$
    """)

    # ----------------------------------------------- 2. datos existentes
    org_id = None
    if _hay_datos():
        org_id = conn.execute(text("""
            INSERT INTO organizaciones (nombre, slug, plan, numero_cobranza_siguiente)
            SELECT COALESCE(
                       (SELECT COALESCE(nombre_fantasia, razon_social) FROM empresa LIMIT 1),
                       'Organización principal'),
                   'principal', 'premium',
                   COALESCE((SELECT MAX(numero) + 1 FROM cobranzas), 1000)
            RETURNING id
        """)).scalar()
    else:
        # Base nueva: la fila de ejemplo de `empresa` no es de nadie.
        op.execute("DELETE FROM empresa")

    # ------------------------------------------ 3. empresa por organización
    op.execute("ALTER TABLE empresa ADD COLUMN organizacion_id UUID")
    if org_id:
        conn.execute(text("UPDATE empresa SET organizacion_id = :o"), {"o": org_id})
    op.execute("ALTER TABLE empresa DROP CONSTRAINT empresa_pkey")
    op.execute("ALTER TABLE empresa DROP COLUMN id")
    op.execute("""
        ALTER TABLE empresa
            ALTER COLUMN organizacion_id SET NOT NULL,
            ADD PRIMARY KEY (organizacion_id),
            ADD FOREIGN KEY (organizacion_id) REFERENCES organizaciones(id)
    """)

    # ------------------------------- 4. organizacion_id en tablas de negocio
    for tabla in TABLAS_TENANT:
        op.execute(f"ALTER TABLE {tabla} ADD COLUMN organizacion_id UUID")
        if org_id:
            conn.execute(text(f"UPDATE {tabla} SET organizacion_id = :o"), {"o": org_id})
        op.execute(f"""
            ALTER TABLE {tabla}
                ALTER COLUMN organizacion_id SET NOT NULL,
                ADD CONSTRAINT fk_{tabla}_organizacion
                    FOREIGN KEY (organizacion_id) REFERENCES organizaciones(id)
        """)
        op.execute(f"CREATE INDEX idx_{tabla}_organizacion ON {tabla}(organizacion_id)")

    # audit_log: nullable (eventos de plataforma no pertenecen a nadie).
    op.execute("ALTER TABLE audit_log ADD COLUMN organizacion_id UUID REFERENCES organizaciones(id)")
    if org_id:
        conn.execute(text("UPDATE audit_log SET organizacion_id = :o"), {"o": org_id})
    op.execute("CREATE INDEX idx_audit_organizacion_fecha ON audit_log(organizacion_id, created_at DESC)")

    # tipos_gestion: NULL = tipo de sistema compartido por todos; con valor =
    # tipo propio que creó un estudio.
    op.execute("ALTER TABLE tipos_gestion ADD COLUMN organizacion_id UUID REFERENCES organizaciones(id)")
    soltar_unicos_de_columna("tipos_gestion", "nombre")
    op.execute("""
        CREATE UNIQUE INDEX uq_tipos_gestion_nombre
            ON tipos_gestion (COALESCE(organizacion_id, '00000000-0000-0000-0000-000000000000'::uuid),
                              lower(nombre))
    """)

    # ------------------------------------------- 5. UNIQUE por organización
    for tabla in ("clientes", "deudores", "pacientes"):
        soltar_unicos_de_columna(tabla, "rut")
        op.execute(f"ALTER TABLE {tabla} ADD CONSTRAINT uq_{tabla}_rut UNIQUE (organizacion_id, rut)")

    # El email identifica a la persona en el login: único en toda la
    # plataforma y sin distinguir mayúsculas.
    soltar_unicos_de_columna("usuarios", "email")
    op.execute("CREATE UNIQUE INDEX uq_usuarios_email ON usuarios (lower(email))")

    # ------------------------------------------- 6. FKs compuestas
    for tabla in TABLAS_PADRE:
        op.execute(f"ALTER TABLE {tabla} ADD CONSTRAINT uq_{tabla}_org_id UNIQUE (organizacion_id, id)")

    for tabla, columna, destino, al_borrar in FKS_COMPUESTAS:
        soltar_fks_de_columna(tabla, columna)
        borrar = f" ON DELETE {al_borrar}" if al_borrar else ""
        op.execute(f"""
            ALTER TABLE {tabla}
                ADD CONSTRAINT fk_{tabla}_{columna}
                FOREIGN KEY (organizacion_id, {columna})
                REFERENCES {destino} (organizacion_id, id){borrar}
        """)

    # ------------------------------------- 7. N° de cobranza por organización
    op.execute("DROP INDEX IF EXISTS idx_cobranzas_numero")
    soltar_unicos_de_columna("cobranzas", "numero")
    op.execute("ALTER TABLE cobranzas ALTER COLUMN numero DROP IDENTITY IF EXISTS")
    op.execute("ALTER TABLE cobranzas ADD CONSTRAINT uq_cobranzas_numero UNIQUE (organizacion_id, numero)")
    op.execute("""
        CREATE FUNCTION asignar_numero_cobranza() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
        AS $$
        BEGIN
            -- Se respeta un N° explícito (migrar la cartera de un sistema
            -- anterior con sus números); si no viene, se toma el siguiente
            -- del correlativo de la organización (el UPDATE bloquea la fila,
            -- así que dos altas simultáneas nunca obtienen el mismo número).
            IF NEW.numero IS NULL THEN
                UPDATE organizaciones
                   SET numero_cobranza_siguiente = numero_cobranza_siguiente + 1
                 WHERE id = NEW.organizacion_id
                RETURNING numero_cobranza_siguiente - 1 INTO NEW.numero;
                IF NEW.numero IS NULL THEN
                    RAISE EXCEPTION 'Organización % inexistente', NEW.organizacion_id;
                END IF;
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER trg_cobranzas_numero
            BEFORE INSERT ON cobranzas
            FOR EACH ROW EXECUTE FUNCTION asignar_numero_cobranza()
    """)
    op.execute("""
        CREATE FUNCTION impedir_cambio_numero() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.numero IS DISTINCT FROM OLD.numero
               OR NEW.organizacion_id IS DISTINCT FROM OLD.organizacion_id THEN
                RAISE EXCEPTION 'El N° de cobranza y la organización no se pueden cambiar';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER trg_cobranzas_numero_fijo
            BEFORE UPDATE ON cobranzas
            FOR EACH ROW EXECUTE FUNCTION impedir_cambio_numero()
    """)

    # Índices para los listados más usados, ya por organización.
    op.execute("CREATE INDEX idx_cobranzas_org_estado ON cobranzas(organizacion_id, estado)")
    op.execute("CREATE INDEX idx_gestiones_org_fecha ON gestiones(organizacion_id, fecha_gestion DESC)")
    op.execute("CREATE INDEX idx_pagos_org_fecha ON pagos(organizacion_id, fecha_pago DESC)")

    # ----------------------------------------------- 8. inmutabilidad en BD
    op.execute("""
        CREATE FUNCTION impedir_modificacion() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Los registros de % son inmutables: se corrigen con un registro nuevo, no editando ni borrando', TG_TABLE_NAME
                USING ERRCODE = 'insufficient_privilege';
        END $$
    """)
    for tabla in ("gestiones", "pagos", "audit_log"):
        op.execute(f"""
            CREATE TRIGGER trg_{tabla}_inmutable
                BEFORE UPDATE OR DELETE ON {tabla}
                FOR EACH ROW EXECUTE FUNCTION impedir_modificacion()
        """)


def downgrade() -> None:
    raise NotImplementedError("Pasar a multi-organización no se revierte: restaurar respaldo.")

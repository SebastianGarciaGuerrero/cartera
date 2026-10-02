"""Seguridad de cuentas: sesiones revocables, 2FA, bloqueo por intentos,
recuperación de contraseña y registro de accesos.

  - `sesiones`: cada inicio de sesión. Guarda SOLO el hash del refresh token
    (si alguien roba la base, no puede usar los tokens). Rotación en cada
    uso y detección de reutilización (señal de token robado).
  - `tokens_un_uso`: enlaces de recuperación de contraseña e invitaciones,
    de un solo uso y con vencimiento corto (también solo el hash).
  - `eventos_acceso`: bitácora inmutable de logins, fallos, bloqueos, 2FA y
    cambios de contraseña (Ley 21.719: trazabilidad de accesos a datos
    personales).
  - usuarios: 2FA (TOTP), contador de intentos fallidos y bloqueo temporal,
    marca de "debe cambiar contraseña", y `cliente_id` para los usuarios del
    portal de mandantes (ven solo la cartera de su empresa).
  - Roles nuevos: abogado, procurador y mandante (portal).

Revisión: 0004
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE usuarios
            ADD COLUMN mfa_activo               BOOLEAN     NOT NULL DEFAULT FALSE,
            ADD COLUMN mfa_secreto_cifrado      TEXT,
            ADD COLUMN mfa_ultimo_paso          BIGINT,
            ADD COLUMN mfa_codigos_recuperacion JSONB       NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN intentos_fallidos        INTEGER     NOT NULL DEFAULT 0,
            ADD COLUMN bloqueado_hasta          TIMESTAMPTZ,
            ADD COLUMN password_actualizada_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            ADD COLUMN debe_cambiar_password    BOOLEAN     NOT NULL DEFAULT FALSE,
            ADD COLUMN cliente_id               UUID,
            ADD CONSTRAINT fk_usuarios_cliente_id FOREIGN KEY (organizacion_id, cliente_id)
                REFERENCES clientes (organizacion_id, id)
    """)
    op.execute("ALTER TABLE usuarios ALTER COLUMN password_hash TYPE TEXT")

    op.execute("""
        INSERT INTO roles (nombre, descripcion) VALUES
            ('abogado',    'Gestiona causas judiciales, escritos y plazos'),
            ('procurador', 'Tramita causas: actuaciones, notificaciones y plazos'),
            ('mandante',   'Usuario del portal de clientes: ve solo la cartera de su empresa')
        ON CONFLICT (nombre) DO NOTHING
    """)

    op.execute("""
        CREATE TABLE sesiones (
            id                    UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            usuario_id            UUID         NOT NULL REFERENCES usuarios(id),
            organizacion_id       UUID         NOT NULL REFERENCES organizaciones(id),
            refresh_hash          CHAR(64)     NOT NULL UNIQUE,
            refresh_anterior_hash CHAR(64),
            creada_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            ultimo_uso_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            expira_at             TIMESTAMPTZ  NOT NULL,
            revocada_at           TIMESTAMPTZ,
            motivo_revocacion     VARCHAR(40),
            ip                    VARCHAR(45),
            user_agent            VARCHAR(300)
        )
    """)
    op.execute("CREATE INDEX idx_sesiones_usuario ON sesiones(usuario_id) WHERE revocada_at IS NULL")
    op.execute("CREATE INDEX idx_sesiones_anterior ON sesiones(refresh_anterior_hash)")

    op.execute("""
        CREATE TABLE tokens_un_uso (
            id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            usuario_id  UUID         NOT NULL REFERENCES usuarios(id),
            proposito   VARCHAR(20)  NOT NULL CHECK (proposito IN ('reset_password', 'invitacion')),
            token_hash  CHAR(64)     NOT NULL UNIQUE,
            expira_at   TIMESTAMPTZ  NOT NULL,
            usado_at    TIMESTAMPTZ,
            ip          VARCHAR(45),
            created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE TABLE eventos_acceso (
            id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            organizacion_id UUID         REFERENCES organizaciones(id),
            usuario_id      UUID         REFERENCES usuarios(id),
            email           VARCHAR(150),
            evento          VARCHAR(40)  NOT NULL,
            exito           BOOLEAN      NOT NULL,
            ip              VARCHAR(45),
            user_agent      VARCHAR(300),
            detalle         JSONB,
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_eventos_acceso_org ON eventos_acceso(organizacion_id, created_at DESC)")
    op.execute("CREATE INDEX idx_eventos_acceso_ip ON eventos_acceso(ip, created_at DESC)")
    op.execute("""
        CREATE TRIGGER trg_eventos_acceso_inmutable
            BEFORE UPDATE OR DELETE ON eventos_acceso
            FOR EACH ROW EXECUTE FUNCTION impedir_modificacion()
    """)


def downgrade() -> None:
    raise NotImplementedError("Restaurar respaldo para volver atrás.")

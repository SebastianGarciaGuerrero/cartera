"""Portal del deudor: enlaces personales para que el deudor vea su estado.

  - `enlaces_deudor`: un enlace por deudor (al generar uno nuevo, el anterior
    queda revocado). Se guarda solo el HASH del token, como las sesiones.
    El deudor además tiene que escribir su RUT para abrirlo; tras varios RUT
    equivocados el enlace se bloquea. Vence solo y se puede desactivar.

La búsqueda por token la hace el código público en modo sistema (todavía
no se sabe la organización); todo lo demás pasa por RLS como siempre.

Revisión: 0009
"""

from alembic import op

from migraciones.utilidades import proteger_tabla_tenant

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE enlaces_deudor (
            id                 UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            organizacion_id    UUID         NOT NULL REFERENCES organizaciones(id),
            deudor_id          UUID         NOT NULL,
            token_hash         CHAR(64)     NOT NULL UNIQUE,
            creado_por         UUID         NOT NULL,
            created_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            expira_at          TIMESTAMPTZ  NOT NULL,
            revocado_at        TIMESTAMPTZ,
            bloqueado_at       TIMESTAMPTZ,
            intentos_fallidos  INTEGER      NOT NULL DEFAULT 0,
            accesos            INTEGER      NOT NULL DEFAULT 0,
            ultimo_acceso_at   TIMESTAMPTZ,
            CONSTRAINT fk_enlaces_deudor_deudor FOREIGN KEY (organizacion_id, deudor_id)
                REFERENCES deudores (organizacion_id, id),
            CONSTRAINT fk_enlaces_deudor_creador FOREIGN KEY (organizacion_id, creado_por)
                REFERENCES usuarios (organizacion_id, id)
        )
    """)
    op.execute("""
        CREATE INDEX idx_enlaces_deudor_vigente ON enlaces_deudor (organizacion_id, deudor_id)
            WHERE revocado_at IS NULL
    """)
    proteger_tabla_tenant("enlaces_deudor")


def downgrade() -> None:
    op.execute("DROP TABLE enlaces_deudor")

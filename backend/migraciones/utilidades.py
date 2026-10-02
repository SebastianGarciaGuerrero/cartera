"""
Ayudas compartidas por las migraciones.

Cada tabla que pertenece a una organización (tenant) debe:
  1. tener la columna organizacion_id NOT NULL,
  2. tener RLS activado con la política de aislamiento,
  3. dar permisos al rol de la aplicación (sin DELETE: nunca se borra físico).

`proteger_tabla_tenant()` hace los pasos 2 y 3. Toda migración que cree una
tabla de negocio nueva tiene que llamarla; el test de aislamiento
(tests/test_aislamiento.py) falla si alguna tabla con organizacion_id
queda sin política.
"""

from pathlib import Path

from alembic import op
from sqlalchemy import text

CARPETA_SQL = Path(__file__).resolve().parent / "sql"

# Rol sin login con el que corre la aplicación dentro de cada transacción
# autenticada (SET LOCAL ROLE). No es dueño de las tablas, así que RLS sí
# se le aplica.
ROL_APP = "cartera_app"


def ejecutar_sql_archivo(nombre: str) -> None:
    """Ejecuta un .sql de migraciones/sql tal cual (sin parsear binds)."""
    sql = (CARPETA_SQL / nombre).read_text(encoding="utf-8")
    op.get_bind().exec_driver_sql(sql)


def existe_tabla(nombre: str) -> bool:
    return op.get_bind().execute(
        text("SELECT to_regclass(:t) IS NOT NULL"), {"t": f"public.{nombre}"}
    ).scalar()


def existe_columna(tabla: str, columna: str) -> bool:
    return op.get_bind().execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t AND column_name = :c"
        ),
        {"t": tabla, "c": columna},
    ).first() is not None


def soltar_fks_de_columna(tabla: str, columna: str) -> None:
    """Elimina las FK de una columna sin conocer su nombre autogenerado."""
    op.execute(f"""
        DO $$
        DECLARE r RECORD;
        BEGIN
            FOR r IN
                SELECT con.conname
                FROM pg_constraint con
                JOIN pg_attribute att
                  ON att.attrelid = con.conrelid AND att.attnum = ANY (con.conkey)
                WHERE con.contype = 'f'
                  AND con.conrelid = 'public.{tabla}'::regclass
                  AND att.attname = '{columna}'
            LOOP
                EXECUTE format('ALTER TABLE public.{tabla} DROP CONSTRAINT %I', r.conname);
            END LOOP;
        END $$;
    """)


def soltar_unicos_de_columna(tabla: str, columna: str) -> None:
    """Elimina los UNIQUE (constraint e índice) que cubren SOLO esa columna."""
    op.execute(f"""
        DO $$
        DECLARE r RECORD;
        BEGIN
            FOR r IN
                SELECT con.conname
                FROM pg_constraint con
                JOIN pg_attribute att
                  ON att.attrelid = con.conrelid AND att.attnum = con.conkey[1]
                WHERE con.contype = 'u'
                  AND array_length(con.conkey, 1) = 1
                  AND con.conrelid = 'public.{tabla}'::regclass
                  AND att.attname = '{columna}'
            LOOP
                EXECUTE format('ALTER TABLE public.{tabla} DROP CONSTRAINT %I', r.conname);
            END LOOP;
            FOR r IN
                SELECT i.relname
                FROM pg_index ix
                JOIN pg_class i ON i.oid = ix.indexrelid
                JOIN pg_attribute att
                  ON att.attrelid = ix.indrelid AND att.attnum = ix.indkey[0]
                WHERE ix.indisunique AND NOT ix.indisprimary
                  AND ix.indnatts = 1
                  AND ix.indrelid = 'public.{tabla}'::regclass
                  AND att.attname = '{columna}'
            LOOP
                EXECUTE format('DROP INDEX public.%I', r.relname);
            END LOOP;
        END $$;
    """)


def proteger_tabla_tenant(tabla: str, lectura_global: bool = False,
                          permisos: str = "SELECT, INSERT, UPDATE") -> None:
    """
    Activa RLS en la tabla y crea la política de aislamiento por organización.

    lectura_global=True: además de las filas propias, se ven las filas con
    organizacion_id NULL (catálogos de sistema compartidos, ej. tipos_gestion).
    Solo se pueden ESCRIBIR filas de la propia organización.
    """
    usando = "organizacion_id = app_organizacion_actual()"
    if lectura_global:
        usando = f"(organizacion_id IS NULL OR {usando})"
    op.execute(f"ALTER TABLE public.{tabla} ENABLE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS aislamiento_organizacion ON public.{tabla}")
    op.execute(f"""
        CREATE POLICY aislamiento_organizacion ON public.{tabla}
            TO {ROL_APP}
            USING ({usando})
            WITH CHECK (organizacion_id = app_organizacion_actual())
    """)
    op.execute(f"GRANT {permisos} ON public.{tabla} TO {ROL_APP}")


def bloquear_tabla_para_app(tabla: str) -> None:
    """
    Tabla de uso interno (sesiones, tokens): el rol de la app no la ve.
    Solo la toca el código de autenticación, que corre como dueño.
    RLS activado sin políticas = nadie salvo el dueño ve filas.
    """
    op.execute(f"ALTER TABLE public.{tabla} ENABLE ROW LEVEL SECURITY")
    op.execute(f"REVOKE ALL ON public.{tabla} FROM {ROL_APP}")

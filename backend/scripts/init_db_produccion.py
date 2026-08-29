"""
Inicializa una base de datos VACÍA (ej. Neon, para la demo) con el esquema
completo, los datos de práctica y los usuarios del equipo.

Uso (desde la carpeta backend, con el venv activo):
    python scripts/init_db_produccion.py "postgresql://usuario:clave@host/db"

⚠️ Solo para bases NUEVAS: si las tablas ya existen, fallará (a propósito,
para no pisar datos).
"""

import sys
from pathlib import Path

import bcrypt
import psycopg2

RAIZ = Path(__file__).resolve().parent.parent.parent
SQLS = [
    RAIZ / "database" / "init" / "001_schema.sql",
    RAIZ / "database" / "init" / "002_verificacion.sql",
]

# Cuentas adicionales al admin que ya crea 002_verificacion.sql.
# Cambiar por las personas reales de la empresa antes de correr el script;
# dejar la lista vacía crea solo el admin.
USUARIOS_EXTRA: list[tuple[str, str, str, int]] = [
    # (nombre, email, password inicial, rol: 1=admin 2=supervisor 3=operador 4=viewer)
]


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    url = sys.argv[1]

    conexion = psycopg2.connect(url)
    conexion.autocommit = False
    cur = conexion.cursor()

    for sql in SQLS:
        print(f"Ejecutando {sql.name}…")
        cur.execute(sql.read_text(encoding="utf-8"))

    print("Creando usuarios del equipo…")
    for nombre, email, password, rol_id in USUARIOS_EXTRA:
        hash_ = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        cur.execute(
            """INSERT INTO usuarios (nombre, email, password_hash, rol_id)
               VALUES (%s, %s, %s, %s) ON CONFLICT (email) DO NOTHING""",
            (nombre, email, hash_, rol_id),
        )

    print("Ajustando secuencia de cobranzas (siguiente ≥ 20000, sin chocar)…")
    cur.execute(
        """SELECT setval(pg_get_serial_sequence('cobranzas','numero'),
                         GREATEST(COALESCE(MAX(numero), 0), 19999))
           FROM cobranzas;"""
    )

    conexion.commit()
    cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
    print(f"Listo: {cur.fetchone()[0]} tablas creadas, datos de práctica cargados.")
    conexion.close()


if __name__ == "__main__":
    main()

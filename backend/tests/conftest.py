"""
Configuración de los tests: una base PostgreSQL REAL y nueva en cada corrida
(las reglas importantes viven en la base: RLS, triggers, FKs compuestas, y
no se pueden probar con SQLite ni con mocks).

De dónde sale el Postgres:
  - TEST_DATABASE_URL (CI, o un Postgres propio): se crea una base temporal
    en ese servidor y se borra al terminar.
  - Si no está definida, se levanta uno portátil con `pgserver` (pip), sin
    Docker.

Uso:  cd backend && pytest
"""

import os
import secrets
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import psycopg2
import pytest

RAIZ_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ_BACKEND))


def _servidor_base() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        return url
    import pgserver  # dependencia de desarrollo

    carpeta = Path(tempfile.gettempdir()) / "cartera_pgtest"
    servidor = pgserver.get_server(str(carpeta), cleanup_mode=None)
    return servidor.get_uri()


def _con_base(url: str, base: str) -> str:
    partes = urlparse(url)
    return urlunparse(partes._replace(path=f"/{base}"))


_URL_SERVIDOR = _servidor_base()
_NOMBRE_BASE = f"cartera_test_{secrets.token_hex(4)}"


def _sql_admin(sql: str) -> None:
    """Ejecuta fuera de transacción (CREATE/DROP DATABASE lo exigen)."""
    conexion = psycopg2.connect(_con_base(_URL_SERVIDOR, "postgres"))
    conexion.autocommit = True
    try:
        conexion.cursor().execute(sql)
    finally:
        conexion.close()


_sql_admin(f"CREATE DATABASE {_NOMBRE_BASE} ENCODING 'UTF8' TEMPLATE template0")

URL_TEST = _con_base(_URL_SERVIDOR, _NOMBRE_BASE)

# Antes de importar la app: el engine se crea al importar app.database.
os.environ["DATABASE_URL"] = URL_TEST
os.environ["ENVIRONMENT"] = "test"
os.environ["SECRET_KEY"] = secrets.token_urlsafe(48)
os.environ["URL_PUBLICA"] = "http://testserver"
os.environ["LIMITE_IP_INTENTOS"] = "1000"

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

_cfg = Config(str(RAIZ_BACKEND / "alembic.ini"))
_cfg.set_main_option("script_location", str(RAIZ_BACKEND / "migraciones"))
_cfg.cmd_opts = type("Opts", (), {"x": [f"url={URL_TEST}"]})()
_dir_anterior = os.getcwd()
os.chdir(RAIZ_BACKEND)
try:
    command.upgrade(_cfg, "head")
finally:
    os.chdir(_dir_anterior)


def pytest_sessionfinish(session, exitstatus):
    from app.database import engine

    engine.dispose()
    try:
        _sql_admin(f"DROP DATABASE IF EXISTS {_NOMBRE_BASE} WITH (FORCE)")
    except Exception:
        pass


# ------------------------------------------------------------ fixtures

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.sesiones import reiniciar_limites_ip  # noqa: E402

PASSWORD = "Clave-Segura-2026"


@pytest.fixture(autouse=True)
def _limpiar_limites():
    reiniciar_limites_ip()
    yield


@pytest.fixture()
def cliente_http():
    with TestClient(app) as c:
        yield c


def crear_organizacion(plan: str = "premium", rol: str = "admin", email: str | None = None):
    """Crea organización + empresa + usuario con contraseña conocida. Devuelve dict."""
    import app.models  # noqa: F401
    from app.models.empresa import Empresa
    from app.models.organizacion import Organizacion
    from app.models.rol import Rol
    from app.models.usuario import Usuario
    from app.security import hashear_password
    from app.tenancy import sesion_sistema

    sufijo = secrets.token_hex(3)
    with sesion_sistema() as db:
        org = Organizacion(nombre=f"Estudio {sufijo}", slug=f"estudio-{sufijo}", plan=plan)
        db.add(org)
        db.flush()
        db.add(Empresa(organizacion_id=org.id, razon_social=f"Estudio {sufijo} SpA",
                       wordmark=f"ESTUDIO {sufijo}", instrucciones_pago="Transferencia"))
        rol_obj = db.query(Rol).filter(Rol.nombre == rol).one()
        usuario = Usuario(
            organizacion_id=org.id,
            nombre=f"Admin {sufijo}",
            email=email or f"admin-{sufijo}@test.cl",
            password_hash=hashear_password(PASSWORD),
            rol_id=rol_obj.id,
        )
        db.add(usuario)
        db.commit()
        return {"org_id": org.id, "usuario_id": usuario.id, "email": usuario.email, "slug": org.slug}


def agregar_usuario(org_id, rol: str, email: str | None = None, cliente_id=None):
    import app.models  # noqa: F401
    from app.models.rol import Rol
    from app.models.usuario import Usuario
    from app.security import hashear_password
    from app.tenancy import sesion_sistema

    with sesion_sistema() as db:
        u = Usuario(
            organizacion_id=org_id,
            nombre=f"{rol} {secrets.token_hex(2)}",
            email=email or f"{rol}-{secrets.token_hex(3)}@test.cl",
            password_hash=hashear_password(PASSWORD),
            rol_id=db.query(Rol).filter(Rol.nombre == rol).one().id,
            cliente_id=cliente_id,
        )
        db.add(u)
        db.commit()
        return u.email


def login(cliente_http, email: str, password: str = PASSWORD) -> dict:
    r = cliente_http.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def org_a():
    return crear_organizacion()


@pytest.fixture()
def org_b():
    return crear_organizacion()


def rut_valido(n: int) -> str:
    """RUT válido distinto por cada n (calcula el DV)."""
    from app.rut import calcular_dv

    cuerpo = 10_000_000 + n * 7919
    return f"{cuerpo}-{calcular_dv(cuerpo)}"


def crear_cartera(cliente_http, headers, monto=100000, n=1) -> dict:
    """Cliente + deudor + cobranza mínimos. Devuelve sus ids."""
    r = cliente_http.post("/api/clientes/", headers=headers,
                          json={"rut": rut_valido(n), "razon_social": f"Mandante {n} SpA"})
    assert r.status_code == 201, r.text
    cliente_id = r.json()["id"]
    r = cliente_http.post("/api/deudores/", headers=headers,
                          json={"rut": rut_valido(n + 1000), "nombre": f"Deudor {n}",
                                "contactos": [{"tipo": "celular", "valor": "+56911112222"}]})
    assert r.status_code == 201, r.text
    deudor_id = r.json()["id"]
    r = cliente_http.post("/api/cobranzas/", headers=headers,
                          json={"cliente_id": cliente_id, "deudor_id": deudor_id,
                                "monto_original": monto, "id_externo": f"EXT-{n}"})
    assert r.status_code == 201, r.text
    return {"cliente_id": cliente_id, "deudor_id": deudor_id,
            "cobranza_id": r.json()["id"], "numero": r.json()["numero"]}

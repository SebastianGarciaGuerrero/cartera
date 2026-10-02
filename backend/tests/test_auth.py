"""
Autenticación: login, bloqueo por fuerza bruta, rotación del refresh token,
logout real, cambio y recuperación de contraseña, 2FA.
"""

import re
import time

import pyotp

from app import mfa
from tests.conftest import PASSWORD, agregar_usuario, crear_organizacion, login

CSRF = {"X-Requested-With": "cartera"}


def test_login_correcto_devuelve_token_y_cookie(cliente_http, org_a):
    r = cliente_http.post("/api/auth/login", json={"email": org_a["email"], "password": PASSWORD})
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["usuario"]["rol"] == "admin"
    assert "cobranzas" in cuerpo["usuario"]["organizacion"]["funciones"]
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/api/auth" in cookie
    assert "password_hash" not in r.text


def test_email_mayusculas_y_mensaje_generico(cliente_http, org_a):
    assert cliente_http.post("/api/auth/login",
                             json={"email": org_a["email"].upper(), "password": PASSWORD}).status_code == 200
    r1 = cliente_http.post("/api/auth/login", json={"email": org_a["email"], "password": "mala-clave-123"})
    r2 = cliente_http.post("/api/auth/login", json={"email": "noexiste@test.cl", "password": "mala-clave-123"})
    assert r1.status_code == r2.status_code == 401
    assert r1.json()["detail"] == r2.json()["detail"]  # no revela si el email existe


def test_bloqueo_tras_intentos_fallidos(cliente_http):
    org = crear_organizacion()
    for _ in range(5):
        cliente_http.post("/api/auth/login", json={"email": org["email"], "password": "incorrecta-123"})
    r = cliente_http.post("/api/auth/login", json={"email": org["email"], "password": PASSWORD})
    assert r.status_code == 429  # ni con la clave correcta mientras dure el bloqueo


def test_sin_token_o_token_invalido(cliente_http):
    assert cliente_http.get("/api/cobranzas/").status_code == 401
    assert cliente_http.get("/api/cobranzas/", headers={"Authorization": "Bearer abc"}).status_code == 401


def test_refresh_rota_y_detecta_reutilizacion(cliente_http, org_a):
    login(cliente_http, org_a["email"])
    viejo = cliente_http.cookies.get("cartera_refresh")

    # Sin la cabecera anti-CSRF se rechaza.
    assert cliente_http.post("/api/auth/refresh").status_code == 403

    r = cliente_http.post("/api/auth/refresh", headers=CSRF)
    assert r.status_code == 200
    nuevo = cliente_http.cookies.get("cartera_refresh")
    assert nuevo and nuevo != viejo

    # Presentar el token viejo fuera de la ventana de gracia = robo → revoca todo.
    from datetime import timedelta
    from app import sesiones
    gracia = sesiones.GRACIA_ROTACION
    sesiones.GRACIA_ROTACION = timedelta(seconds=0)
    try:
        cliente_http.cookies.set("cartera_refresh", viejo, path="/api/auth")
        assert cliente_http.post("/api/auth/refresh", headers=CSRF).status_code == 401
        cliente_http.cookies.set("cartera_refresh", nuevo, path="/api/auth")
        assert cliente_http.post("/api/auth/refresh", headers=CSRF).status_code == 401
    finally:
        sesiones.GRACIA_ROTACION = gracia


def test_logout_invalida_el_access_token_al_instante(cliente_http, org_a):
    h = login(cliente_http, org_a["email"])
    assert cliente_http.get("/api/auth/me", headers=h).status_code == 200
    assert cliente_http.post("/api/auth/logout", headers=CSRF).status_code == 204
    assert cliente_http.get("/api/auth/me", headers=h).status_code == 401


def test_cambiar_password_cierra_las_otras_sesiones(cliente_http, org_a):
    h1 = login(cliente_http, org_a["email"])
    h2 = login(cliente_http, org_a["email"])
    r = cliente_http.put("/api/auth/cambiar-password", headers=h1,
                         json={"password_actual": PASSWORD, "password_nueva": "123"})
    assert r.status_code == 422  # política: muy corta
    r = cliente_http.put("/api/auth/cambiar-password", headers=h1,
                         json={"password_actual": PASSWORD, "password_nueva": "Otra-Clave-Larga-99"})
    assert r.status_code == 204
    assert cliente_http.get("/api/auth/me", headers=h1).status_code == 200  # la actual sigue
    assert cliente_http.get("/api/auth/me", headers=h2).status_code == 401  # las otras no
    login(cliente_http, org_a["email"], "Otra-Clave-Larga-99")


def test_recuperar_y_restablecer(cliente_http, org_a, monkeypatch):
    enviados = []
    monkeypatch.setattr("app.routers.auth.enviar_correo",
                        lambda dest, asunto, texto, html=None: enviados.append(texto))
    assert cliente_http.post("/api/auth/recuperar", json={"email": "nadie@test.cl"}).status_code == 202
    assert enviados == []
    assert cliente_http.post("/api/auth/recuperar", json={"email": org_a["email"]}).status_code == 202
    token = re.search(r"token=([\w-]+)", enviados[0]).group(1)

    r = cliente_http.post("/api/auth/restablecer", json={"token": token, "password_nueva": "Nueva-Clave-2026!"})
    assert r.status_code == 204
    # Un solo uso.
    r = cliente_http.post("/api/auth/restablecer", json={"token": token, "password_nueva": "Otra-Mas-2026!!"})
    assert r.status_code == 400
    login(cliente_http, org_a["email"], "Nueva-Clave-2026!")


def test_2fa_completo(cliente_http):
    org = crear_organizacion()
    h = login(cliente_http, org["email"])
    inicio = cliente_http.post("/api/auth/mfa/iniciar", headers=h).json()
    assert inicio["qr"].startswith("data:image/svg+xml")
    totp = pyotp.TOTP(inicio["secreto"])

    assert cliente_http.post("/api/auth/mfa/confirmar", headers=h, json={"codigo": "000000"}).status_code == 400
    r = cliente_http.post("/api/auth/mfa/confirmar", headers=h, json={"codigo": totp.now()})
    assert r.status_code == 200
    codigos = r.json()["codigos"]
    assert len(codigos) == 10

    # Ahora el login pide el segundo factor.
    r = cliente_http.post("/api/auth/login", json={"email": org["email"], "password": PASSWORD})
    assert r.json()["requiere_mfa"] is True
    mfa_token = r.json()["mfa_token"]

    # El mismo código ya usado no sirve (anti-replay): se usa uno de recuperación.
    r = cliente_http.post("/api/auth/login/mfa", json={"mfa_token": mfa_token, "codigo": codigos[0]})
    assert r.status_code == 200
    # El código de recuperación es de un solo uso.
    r = cliente_http.post("/api/auth/login", json={"email": org["email"], "password": PASSWORD})
    r = cliente_http.post("/api/auth/login/mfa", json={"mfa_token": r.json()["mfa_token"], "codigo": codigos[0]})
    assert r.status_code == 401


def test_semilla_2fa_se_guarda_cifrada():
    cifrado = mfa.cifrar("JBSWY3DPEHPK3PXP")
    assert "JBSWY3DPEHPK3PXP" not in cifrado
    assert mfa.descifrar(cifrado) == "JBSWY3DPEHPK3PXP"


def test_viewer_solo_lectura_y_mandante_sin_api_interna(cliente_http, org_a):
    hv = login(cliente_http, agregar_usuario(org_a["org_id"], "viewer"))
    assert cliente_http.get("/api/cobranzas/", headers=hv).status_code == 200
    r = cliente_http.post("/api/clientes/", headers=hv, json={"rut": "11.111.111-1", "razon_social": "X"})
    assert r.status_code == 403

    ha = login(cliente_http, org_a["email"])
    r = cliente_http.post("/api/clientes/", headers=ha, json={"rut": "11.111.111-1", "razon_social": "Mandante"})
    assert r.status_code == 201
    assert r.json()["rut"] == "11111111-1"  # normalizado
    hm = login(cliente_http, agregar_usuario(org_a["org_id"], "mandante", cliente_id=r.json()["id"]))
    assert cliente_http.get("/api/cobranzas/", headers=hm).status_code == 403


def test_organizacion_suspendida_no_entra(cliente_http):
    from app.models.organizacion import Organizacion
    from app.tenancy import sesion_sistema

    org = crear_organizacion()
    h = login(cliente_http, org["email"])
    with sesion_sistema() as db:
        db.get(Organizacion, org["org_id"]).estado = "suspendida"
        db.commit()
    assert cliente_http.get("/api/auth/me", headers=h).status_code == 403
    r = cliente_http.post("/api/auth/login", json={"email": org["email"], "password": PASSWORD})
    assert r.status_code == 403


def test_cabeceras_de_seguridad(cliente_http):
    r = cliente_http.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"

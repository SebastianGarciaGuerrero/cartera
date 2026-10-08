"""
Portal del deudor: enlace personal + RUT. El deudor ve solo lo suyo y nada
interno del estudio (gestiones, notas, honorarios, equipo).
"""

from datetime import timedelta

from app.indicadores import hoy_chile
from app.rut import rut_con_puntos
from tests.conftest import crear_cartera, crear_organizacion, login, rut_valido


def _token(url: str) -> str:
    assert "/estado#t=" in url
    return url.split("#t=", 1)[1]


def _abrir(cliente_http, token: str, rut: str):
    return cliente_http.post("/api/publico/estado", json={"token": token, "rut": rut})


def test_portal_del_deudor(cliente_http, org_a, org_b):
    h = login(cliente_http, org_a["email"])
    cartera = crear_cartera(cliente_http, h, monto=300_000, n=60)
    rut = rut_valido(1060)  # el RUT del deudor que arma crear_cartera
    hoy = hoy_chile()
    acuerdo = cliente_http.post("/api/acuerdos/", headers=h, json={
        "cobranza_id": cartera["cobranza_id"], "monto_total_acordado": 300000, "numero_cuotas": 3,
        "fecha_primera_cuota": (hoy - timedelta(days=40)).isoformat()}).json()
    primera = min(acuerdo["cuotas"], key=lambda c: c["numero_cuota"])
    r = cliente_http.post("/api/pagos/", headers=h, json={
        "cobranza_id": cartera["cobranza_id"], "cuota_id": primera["id"], "monto": 100000,
        "capital": 80000, "honorarios": 20000, "fecha_pago": hoy.isoformat()})
    assert r.status_code == 201, r.text
    nota = next(t["id"] for t in cliente_http.get("/api/gestiones/tipos", headers=h).json() if t["codigo"] == "nota")
    cliente_http.post("/api/gestiones/", headers=h, json={
        "cobranza_id": cartera["cobranza_id"], "tipo_id": nota, "descripcion": "NOTA INTERNA secreta"})

    ruta = f"/api/deudores/{cartera['deudor_id']}/enlace"
    assert cliente_http.get(ruta, headers=h).json() is None
    nuevo = cliente_http.post(ruta, headers=h)
    assert nuevo.status_code == 201, nuevo.text
    token = _token(nuevo.json()["url"])
    assert token not in str(cliente_http.get(ruta, headers=h).json())  # el token no se vuelve a mostrar

    # Otra organización no ve ni genera enlaces de este deudor.
    hb = login(cliente_http, org_b["email"])
    assert cliente_http.post(ruta, headers=hb).status_code == 404

    # Sin el RUT correcto no se ve nada.
    assert _abrir(cliente_http, token, rut_valido(999)).status_code == 400
    assert _abrir(cliente_http, token, "12.345.678-0").status_code == 422
    assert _abrir(cliente_http, "x" * 43, rut).status_code == 404

    r = _abrir(cliente_http, token, rut_con_puntos(rut))
    assert r.status_code == 200, r.text
    estado = r.json()
    deuda = estado["deudas"][0]
    assert deuda["numero"] == cartera["numero"] and deuda["acreedor"] == "Mandante 60 SpA"
    convenio = deuda["convenio"]
    assert convenio["cuotas_pagadas"] == 1 and convenio["cuotas_atrasadas"] == 1
    assert convenio["proxima"]["numero"] == 3
    assert float(convenio["monto_atrasado"]) == 100000
    assert deuda["como_pagar"] == "Transferencia"
    texto = r.text
    assert "NOTA INTERNA" not in texto and "honorarios" not in texto and "Admin" not in texto

    # El equipo ve que el deudor lo abrió: una gestión automática al día, no una por visita.
    _abrir(cliente_http, token, rut)
    historial = cliente_http.get("/api/gestiones/", params={"cobranza_id": cartera["cobranza_id"]}, headers=h).json()
    assert sum("abrió su estado de cuenta" in g["descripcion"] for g in historial) == 1
    vista = cliente_http.get(ruta, headers=h).json()
    assert vista["accesos"] == 2 and vista["ultimo_acceso_at"]

    # Generar otro enlace revoca el anterior; desactivarlo lo deja sin efecto.
    token2 = _token(cliente_http.post(ruta, headers=h).json()["url"])
    assert _abrir(cliente_http, token, rut).status_code == 404
    assert _abrir(cliente_http, token2, rut).status_code == 200
    assert cliente_http.delete(ruta, headers=h).status_code == 204
    assert _abrir(cliente_http, token2, rut).status_code == 404


def test_enlace_se_bloquea_con_rut_equivocado(cliente_http, org_a):
    h = login(cliente_http, org_a["email"])
    cartera = crear_cartera(cliente_http, h, n=61)
    token = _token(cliente_http.post(f"/api/deudores/{cartera['deudor_id']}/enlace", headers=h).json()["url"])
    for _ in range(4):
        assert _abrir(cliente_http, token, rut_valido(998)).status_code == 400
    assert _abrir(cliente_http, token, rut_valido(998)).status_code == 423
    # Bloqueado, ni con el RUT correcto se abre.
    assert _abrir(cliente_http, token, rut_valido(1061)).status_code == 423
    assert cliente_http.get(f"/api/deudores/{cartera['deudor_id']}/enlace", headers=h).json()["bloqueado"]


def test_portal_del_deudor_es_del_plan_profesional(cliente_http):
    base = crear_organizacion(plan="base")
    h = login(cliente_http, base["email"])
    cartera = crear_cartera(cliente_http, h, n=62)
    assert cliente_http.post(f"/api/deudores/{cartera['deudor_id']}/enlace", headers=h).status_code == 402

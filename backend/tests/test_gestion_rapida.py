"""
Gestión en un paso (con promesa o acuerdo), comentario en los pagos, avisos
de la campana y el panel "Mi seguimiento".
"""

from datetime import timedelta

from app.indicadores import hoy_chile
from tests.conftest import agregar_usuario, crear_cartera, login


def _completa(cliente_http, h, **datos):
    return cliente_http.post("/api/gestiones/completa", headers=h, json=datos)


def _historial(cliente_http, h, cobranza_id):
    return cliente_http.get("/api/gestiones/", params={"cobranza_id": cobranza_id}, headers=h).json()


def test_gestion_con_acuerdo_manual_en_un_paso(cliente_http, org_a):
    h = login(cliente_http, org_a["email"])
    cartera = crear_cartera(cliente_http, h, monto=500_000, n=70)
    hoy = hoy_chile()
    llamada = next(t["id"] for t in cliente_http.get("/api/gestiones/tipos", headers=h).json()
                   if t["codigo"] == "llamada")
    cuotas = [
        {"fecha_vencimiento": (hoy + timedelta(days=10)).isoformat(), "monto": 150000},
        {"fecha_vencimiento": (hoy + timedelta(days=40)).isoformat(), "monto": 150000},
        {"fecha_vencimiento": (hoy + timedelta(days=70)).isoformat(), "monto": 100000},
    ]
    # Si las cuotas no cuadran con el total, no se guarda nada.
    malo = _completa(cliente_http, h, cobranza_id=cartera["cobranza_id"], resultado="acuerdo", tipo_id=llamada,
                     acuerdo={"monto_total_acordado": 450000, "pie": 50000, "numero_cuotas": 3,
                              "fecha_primera_cuota": cuotas[0]["fecha_vencimiento"], "cuotas": cuotas[:2]})
    assert malo.status_code == 422
    assert _historial(cliente_http, h, cartera["cobranza_id"]) == []

    r = _completa(cliente_http, h, cobranza_id=cartera["cobranza_id"], resultado="acuerdo", tipo_id=llamada,
                  descripcion="Acepta pagar en tres partes, la última más chica.",
                  acuerdo={"monto_total_acordado": 450000, "pie": 50000, "numero_cuotas": 1,
                           "fecha_primera_cuota": cuotas[0]["fecha_vencimiento"], "cuotas": cuotas})
    assert r.status_code == 201, r.text
    texto = r.json()["descripcion"]
    assert "ACUERDO DE PAGO: $450.000 en 3 cuota(s) de montos distintos, pie de $50.000" in texto
    assert "Vía: Llamada telefónica." in texto and "la última más chica" in texto

    acuerdo = cliente_http.get("/api/acuerdos/", params={"cobranza_id": cartera["cobranza_id"]}, headers=h).json()[0]
    detalle = cliente_http.get(f"/api/acuerdos/{acuerdo['id']}", headers=h).json()
    assert [float(c["monto"]) for c in detalle["cuotas"]] == [150000, 150000, 100000]
    assert detalle["numero_cuotas"] == 3
    assert cliente_http.get(f"/api/cobranzas/{cartera['cobranza_id']}", headers=h).json()["estado"] == "acuerdo_pago"
    assert len(_historial(cliente_http, h, cartera["cobranza_id"])) == 1  # una sola gestión

    # Un segundo acuerdo vigente se rechaza y tampoco deja gestión suelta.
    otra = _completa(cliente_http, h, cobranza_id=cartera["cobranza_id"], resultado="acuerdo", descripcion="x",
                     acuerdo={"monto_total_acordado": 100, "numero_cuotas": 1,
                              "fecha_primera_cuota": hoy.isoformat()})
    assert otra.status_code == 400
    assert len(_historial(cliente_http, h, cartera["cobranza_id"])) == 1


def test_promesa_y_gestion_simple(cliente_http, org_a):
    h = login(cliente_http, org_a["email"])
    cartera = crear_cartera(cliente_http, h, n=71)
    hoy = hoy_chile()
    assert _completa(cliente_http, h, cobranza_id=cartera["cobranza_id"]).status_code == 422  # sin texto
    assert _completa(cliente_http, h, cobranza_id=cartera["cobranza_id"], resultado="promesa",
                     promesa={"fecha": (hoy - timedelta(days=1)).isoformat()}).status_code == 422

    r = _completa(cliente_http, h, cobranza_id=cartera["cobranza_id"], resultado="promesa",
                  promesa={"fecha": hoy.isoformat(), "monto": 80000})
    assert r.status_code == 201, r.text
    assert r.json()["descripcion"].startswith("PROMESA DE PAGO de $80.000 para el")
    assert r.json()["fecha_proximo_contacto"] == hoy.isoformat()
    items = cliente_http.get("/api/agenda/hoy", headers=h).json()
    assert any(i["tipo"] == "promesa" and i["cobranza_id"] == cartera["cobranza_id"] for i in items)

    r = _completa(cliente_http, h, cobranza_id=cartera["cobranza_id"], descripcion="No contesta",
                  fecha_proximo_contacto=(hoy + timedelta(days=2)).isoformat())
    assert r.status_code == 201 and r.json()["descripcion"] == "No contesta"


def test_pago_con_comentario(cliente_http, org_a):
    h = login(cliente_http, org_a["email"])
    cartera = crear_cartera(cliente_http, h, monto=200_000, n=72)
    r = cliente_http.post("/api/pagos/", headers=h, json={
        "cobranza_id": cartera["cobranza_id"], "monto": 50000, "capital": 50000,
        "observaciones": "Pagó en efectivo en la oficina"})
    assert r.status_code == 201, r.text
    ultima = _historial(cliente_http, h, cartera["cobranza_id"])[0]
    assert "abono por un total de $50.000" in ultima["descripcion"]
    assert "Pagó en efectivo en la oficina" in ultima["descripcion"]


def test_avisos_llegan_a_quien_registro_el_acuerdo(cliente_http, org_a):
    h = login(cliente_http, org_a["email"])
    ho = login(cliente_http, agregar_usuario(org_a["org_id"], "operador"))
    cartera = crear_cartera(cliente_http, h, n=73)
    # La cobranza está asignada al admin, pero el acuerdo lo registra el operador.
    yo = cliente_http.get("/api/auth/me", headers=h).json()["id"]
    assert cliente_http.put(f"/api/cobranzas/{cartera['cobranza_id']}", headers=h,
                            json={"ejecutivo_id": yo}).status_code == 200
    manana = hoy_chile() + timedelta(days=1)
    r = _completa(cliente_http, ho, cobranza_id=cartera["cobranza_id"], resultado="acuerdo",
                  acuerdo={"monto_total_acordado": 60000, "numero_cuotas": 2,
                           "fecha_primera_cuota": manana.isoformat()})
    assert r.status_code == 201, r.text

    for headers in (ho, h):  # quien lo pactó y el ejecutivo asignado
        avisos = cliente_http.get("/api/agenda/avisos", headers=headers).json()
        assert any(i["tipo"] == "cuota" and i["cobranza_id"] == cartera["cobranza_id"] for i in avisos["manana"])
        assert avisos["hoy"] == [] or all(i["fecha"] == hoy_chile().isoformat() for i in avisos["hoy"])


def test_mi_seguimiento(cliente_http, org_a):
    h = login(cliente_http, org_a["email"])
    email_op = agregar_usuario(org_a["org_id"], "operador")
    ho = login(cliente_http, email_op)
    cartera = crear_cartera(cliente_http, h, monto=300_000, n=74)
    hoy = hoy_chile()
    llamada = next(t["id"] for t in cliente_http.get("/api/gestiones/tipos", headers=h).json()
                   if t["codigo"] == "llamada")

    _completa(cliente_http, ho, cobranza_id=cartera["cobranza_id"], tipo_id=llamada, descripcion="Contesta")
    _completa(cliente_http, ho, cobranza_id=cartera["cobranza_id"], resultado="promesa",
              promesa={"fecha": hoy.isoformat(), "monto": 50000})
    _completa(cliente_http, ho, cobranza_id=cartera["cobranza_id"], resultado="acuerdo",
              acuerdo={"monto_total_acordado": 300000, "numero_cuotas": 3,
                       "fecha_primera_cuota": (hoy - timedelta(days=20)).isoformat()})
    cliente_http.post("/api/pagos/", headers=ho, json={
        "cobranza_id": cartera["cobranza_id"], "monto": 50000, "capital": 50000})

    s = cliente_http.get("/api/seguimiento", headers=ho).json()
    assert s["hoy"]["gestiones"] == 4  # llamada, promesa, acuerdo y el abono
    assert s["hoy"]["contactos"] == 1 and s["hoy"]["promesas"] == 1 and s["hoy"]["acuerdos"] == 1
    assert s["periodo"]["promesas_cumplidas"] == 1  # pagó dentro del plazo prometido
    assert s["periodo"]["pagos_registrados"] == 1 and float(s["periodo"]["monto_pagos"]) == 50000
    assert s["acuerdos_vigentes"] == 1 and s["acuerdos_al_dia"] == 0
    assert s["atrasados"][0]["cuotas_atrasadas"] == 1
    assert s["por_dia"][-1]["gestiones"] == 4 and len(s["por_dia"]) == 30
    assert len(s["ultimas"]) == 4

    # El operador no ve el panel de otra persona; el admin sí.
    assert cliente_http.get("/api/seguimiento", headers=ho,
                            params={"usuario_id": cliente_http.get("/api/auth/me", headers=h).json()["id"]}
                            ).status_code == 403
    otro = cliente_http.get("/api/seguimiento", headers=h, params={"usuario_id": s["usuario_id"]})
    assert otro.status_code == 200 and otro.json()["hoy"]["gestiones"] == 4

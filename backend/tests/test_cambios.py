"""
Todo cambio sobre un caso queda en el historial como gestión de quien lo
hizo: gastos, etapa, documentos, datos de la cobranza y del deudor.
"""

from tests.conftest import crear_cartera, login


def _historial(cliente_http, h, cobranza_id):
    r = cliente_http.get("/api/gestiones/", params={"cobranza_id": cobranza_id}, headers=h)
    return [g["descripcion"] for g in r.json()]


def test_cambios_dejan_gestion(cliente_http, org_a):
    h = login(cliente_http, org_a["email"])
    cartera = crear_cartera(cliente_http, h, n=311)
    cid = cartera["cobranza_id"]
    yo = cliente_http.get("/api/auth/me", headers=h).json()["id"]

    # Un cambio de datos no saca a la cobranza de "ingreso".
    cliente_http.put(f"/api/deudores/{cartera['deudor_id']}", headers=h, json={"comuna": "Valparaíso"})
    assert cliente_http.get(f"/api/cobranzas/{cid}", headers=h).json()["etapa"] == "ingreso"
    cliente_http.post(f"/api/cobranzas/{cid}/etapa", headers=h,
                      json={"etapa": "para_demanda", "motivo": "Sin respuesta"})
    r = cliente_http.post("/api/gastos/", headers=h, json={
        "cobranza_id": cid, "tipo": "receptor", "concepto": "Búsqueda negativa", "monto": 15000,
        "proveedor": "Receptor Pérez", "numero_boleta": "123"})
    assert r.status_code == 201, r.text
    cliente_http.put(f"/api/gastos/{r.json()['id']}", headers=h, json={"monto": 18000})
    cliente_http.post(f"/api/cobranzas/{cid}/documentos", headers=h,
                      json={"tipo": "cheque", "numero": "998", "monto": 50000})
    cliente_http.put(f"/api/cobranzas/{cid}", headers=h, json={"id_externo": "SAP-1"})
    cliente_http.post(f"/api/deudores/{cartera['deudor_id']}/contactos", headers=h,
                      json={"tipo": "email", "valor": "nuevo@correo.cl"})

    textos = " | ".join(_historial(cliente_http, h, cid))
    assert "GASTO REGISTRADO: Receptor — Búsqueda negativa, $15.000, Receptor Pérez, boleta N° 123." in textos
    assert "GASTO MODIFICADO (Búsqueda negativa): Monto: 15.000 → 18.000." in textos
    assert "CAMBIO DE ETAPA: Ingreso → Para demanda. Motivo: Sin respuesta." in textos
    assert "DOCUMENTO AGREGADO: Cheque N° 998, $50.000." in textos
    assert "DATOS DE LA COBRANZA MODIFICADOS: ID cliente: EXT-311 → SAP-1." in textos
    assert "CONTACTO AGREGADO: correo nuevo@correo.cl." in textos
    assert "DATOS DEL DEUDOR MODIFICADOS: Comuna: — → Valparaíso." in textos
    gestiones = cliente_http.get("/api/gestiones/", params={"cobranza_id": cid}, headers=h).json()
    assert all(g["usuario_id"] == yo for g in gestiones)


def test_reincidente_y_cuentas_separadas(cliente_http, org_a):
    from datetime import timedelta
    from app.indicadores import hoy_chile

    h = login(cliente_http, org_a["email"])
    cartera = crear_cartera(cliente_http, h, monto=1000, n=321)
    vieja = cartera["cobranza_id"]
    # Paga todo ayer: la primera cobranza queda cerrada.
    r = cliente_http.post("/api/pagos/", headers=h, json={
        "cobranza_id": vieja, "monto": 1000, "capital": 1000,
        "fecha_pago": (hoy_chile() - timedelta(days=1)).isoformat()})
    assert r.status_code == 201, r.text
    ficha = cliente_http.get(f"/api/deudores/{cartera['deudor_id']}", headers=h).json()
    assert ficha["reincidente"] is False and ficha["cobranzas_cerradas"] == 1

    # Vuelve a deber: es el mismo deudor (mismo RUT), con una cuenta nueva y aparte.
    nueva = cliente_http.post("/api/cobranzas/", headers=h, json={
        "cliente_id": cartera["cliente_id"], "deudor_id": cartera["deudor_id"],
        "monto_original": 5000, "id_externo": "EXT-321-B"}).json()["id"]
    ficha = cliente_http.get(f"/api/deudores/{cartera['deudor_id']}", headers=h).json()
    assert ficha["reincidente"] is True
    rut = ficha["rut"]
    encontrado = cliente_http.get("/api/deudores/buscar", headers=h, params={"q": rut}).json()
    assert encontrado[0]["reincidente"] is True

    # Un cambio del deudor queda en UNA cobranza (la abierta), no en la cerrada.
    cliente_http.post(f"/api/deudores/{cartera['deudor_id']}/contactos", headers=h,
                      json={"tipo": "email", "valor": "vuelve@correo.cl"})
    assert any("vuelve@correo.cl" in t for t in _historial(cliente_http, h, nueva))
    assert not any("vuelve@correo.cl" in t for t in _historial(cliente_http, h, vieja))

    # Con dos abiertas, solo en la que se elige: no se duplica.
    tercera = cliente_http.post("/api/cobranzas/", headers=h, json={
        "cliente_id": cartera["cliente_id"], "deudor_id": cartera["deudor_id"],
        "monto_original": 7000, "id_externo": "EXT-321-C"}).json()["id"]
    cliente_http.post(f"/api/deudores/{cartera['deudor_id']}/contactos", headers=h,
                      params={"cobranza_id": nueva}, json={"tipo": "celular", "valor": "+56977776666"})
    assert any("+56977776666" in t for t in _historial(cliente_http, h, nueva))
    assert not any("+56977776666" in t for t in _historial(cliente_http, h, tercera))

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

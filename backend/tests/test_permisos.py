"""
Roles y permisos: lo que un ejecutivo puede y no puede hacer, y que la
administración puede ajustar la tabla.
"""

from tests.conftest import agregar_usuario, crear_cartera, login, rut_valido


def test_ejecutivo_trabaja_sus_casos_pero_no_ve_totales(cliente_http, org_a):
    h = login(cliente_http, org_a["email"])
    cartera = crear_cartera(cliente_http, h, n=301)
    ho = login(cliente_http, agregar_usuario(org_a["org_id"], "operador"))
    me = cliente_http.get("/api/auth/me", headers=ho).json()
    assert "cobranzas_crear" not in me["permisos"] and "ver_totales" not in me["permisos"]

    # Gestiona (la columna vertebral), pero no ingresa cobranzas ni clientes.
    r = cliente_http.post("/api/gestiones/completa", headers=ho, json={
        "cobranza_id": cartera["cobranza_id"], "descripcion": "Llamada, no contesta"})
    assert r.status_code == 201, r.text
    assert cliente_http.post("/api/cobranzas/", headers=ho, json={
        "cliente_id": cartera["cliente_id"], "deudor_id": cartera["deudor_id"], "monto_original": 1000}).status_code == 403
    assert cliente_http.post("/api/clientes/", headers=ho,
                             json={"rut": rut_valido(302), "razon_social": "X"}).status_code == 403
    assert cliente_http.put(f"/api/clientes/{cartera['cliente_id']}", headers=ho,
                            json={"razon_social": "Y"}).status_code == 403

    # Los totales de la cartera, no; los gastos de un caso, sí.
    assert cliente_http.get("/api/cobranzas/resumen-etapas", headers=ho).status_code == 403
    assert cliente_http.get("/api/gastos/resumen", headers=ho).status_code == 403
    assert cliente_http.get("/api/gastos/", headers=ho).status_code == 403
    assert cliente_http.get("/api/gastos/", headers=ho,
                            params={"cobranza_id": cartera["cobranza_id"]}).status_code == 200
    assert cliente_http.post("/api/importar/cobranzas", headers=ho).status_code == 403

    # Recomienda pasar a demanda; presentarla es del abogado o la administración.
    r = cliente_http.post(f"/api/cobranzas/{cartera['cobranza_id']}/etapa", headers=ho,
                          json={"etapa": "para_demanda", "motivo": "No paga hace 90 días"})
    assert r.status_code == 200, r.text
    assert cliente_http.post("/api/judicial/causas", headers=ho, json={}).status_code == 403


def test_administracion_ajusta_permisos(cliente_http, org_a):
    h = login(cliente_http, org_a["email"])
    ho = login(cliente_http, agregar_usuario(org_a["org_id"], "operador"))
    assert cliente_http.put("/api/permisos", headers=ho, json={"roles": {"operador": ["ver_totales"]}}).status_code == 403
    r = cliente_http.put("/api/permisos", headers=h,
                         json={"roles": {"operador": ["cobranzas_crear", "ver_totales"]}})
    assert r.status_code == 200, r.text
    assert r.json()["roles"]["operador"] == ["cobranzas_crear", "ver_totales"]
    assert cliente_http.get("/api/cobranzas/resumen-etapas", headers=ho).status_code == 200
    # El administrador siempre lo puede todo.
    assert cliente_http.put("/api/permisos", headers=h, json={"roles": {"admin": []}}).status_code == 422
    # Volver a lo de antes para no afectar otros tests.
    defecto = cliente_http.get("/api/permisos", headers=h).json()["por_defecto"]["operador"]
    cliente_http.put("/api/permisos", headers=h, json={"roles": {"operador": defecto}})

"""
Ciclo de vida de la cobranza y módulo judicial: etapas, demanda con varias
cobranzas, trámites con plazo, embargos, término de la causa y gastos con
rendición al cliente.
"""

from datetime import timedelta

import psycopg2
import pytest

from app.indicadores import hoy_chile
from tests.conftest import URL_TEST, crear_cartera, crear_organizacion, login


def _otra_cobranza(cliente_http, h, cartera, monto=50_000, externo="EXT-B"):
    r = cliente_http.post("/api/cobranzas/", headers=h, json={
        "cliente_id": cartera["cliente_id"], "deudor_id": cartera["deudor_id"],
        "monto_original": monto, "id_externo": externo})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _ciclo(cliente_http, h, cobranza_id):
    r = cliente_http.get(f"/api/cobranzas/{cobranza_id}/ciclo", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _tipo(cliente_http, h, codigo):
    tipos = cliente_http.get("/api/judicial/tipos-tramite", headers=h).json()
    return next(t for t in tipos if t["codigo"] == codigo)


def _tribunal(cliente_http, h):
    return cliente_http.get("/api/judicial/tribunales", headers=h).json()[0]


def _demanda(cliente_http, h, cobranza_ids, **extra):
    r = cliente_http.post("/api/judicial/causas", headers=h, json={
        "cobranza_ids": cobranza_ids, "rol": extra.pop("rol", "C-1234-2026"),
        "tribunal_id": extra.pop("tribunal_id", _tribunal(cliente_http, h)["id"]),
        "procedimiento": extra.pop("procedimiento", "ejecutivo"), **extra})
    return r


def test_ciclo_de_vida_hasta_la_demanda(cliente_http, org_a):
    h = login(cliente_http, org_a["email"])
    cartera = crear_cartera(cliente_http, h, monto=300_000, n=201)
    cob = cartera["cobranza_id"]

    ciclo = _ciclo(cliente_http, h, cob)
    assert ciclo["etapa"] == "ingreso" and ciclo["paso_actual"] == "ingreso"
    assert [p["estado"] for p in ciclo["pasos"]][:2] == ["actual", "pendiente"]

    # La primera gestión la pasa sola a extrajudicial (y queda en el historial).
    r = cliente_http.post("/api/gestiones/", headers=h, json={"cobranza_id": cob, "descripcion": "Llamada"})
    assert r.status_code == 201
    ciclo = _ciclo(cliente_http, h, cob)
    assert ciclo["etapa"] == "extrajudicial"
    assert ciclo["historial"][-1]["motivo"] == "Primera gestión registrada"
    assert ciclo["historial"][-1]["usuario"]

    r = cliente_http.post(f"/api/cobranzas/{cob}/etapa", headers=h,
                          json={"etapa": "para_demanda", "motivo": "No contesta hace 4 meses"})
    assert r.status_code == 200, r.text
    assert r.json()["paso_actual"] == "para_demanda"
    para = cliente_http.get("/api/judicial/para-demanda", headers=h).json()
    assert [c["id"] for c in para["preparacion"]] == [cob]

    # Demanda con dos cobranzas del mismo deudor: una sola causa, un rol.
    otra = _otra_cobranza(cliente_http, h, cartera)
    r = _demanda(cliente_http, h, [cob, otra])
    assert r.status_code == 201, r.text
    causa = r.json()
    assert sorted(c["id"] for c in causa["cobranzas"]) == sorted([cob, otra])
    assert float(causa["cuantia"]) == 350_000
    assert causa["caratula"] == "Mandante 201 SpA con Deudor 201"
    # Queda el primer trámite con su plazo y el que sigue.
    assert causa["tramites"][0]["tipo_nombre"] == "Se presenta demanda y documentos al tribunal"
    assert causa["plazo_fecha"] == (hoy_chile() + timedelta(days=10)).isoformat()
    assert causa["siguiente_nombre"] == "Distribución e ingreso de rol"

    for c in (cob, otra):
        ciclo = _ciclo(cliente_http, h, c)
        assert ciclo["etapa"] == "judicial" and ciclo["paso_actual"] == "demanda"
        assert ciclo["causas"][0]["rol"] == "C-1234-2026"
    historial = cliente_http.get("/api/gestiones/", params={"cobranza_id": otra}, headers=h).json()
    assert historial[0]["descripcion"].startswith("DEMANDA PRESENTADA: Juicio ejecutivo, rol C-1234-2026")

    # De judicial no se vuelve: ni por la API ni directo en la base.
    r = cliente_http.post(f"/api/cobranzas/{cob}/etapa", headers=h, json={"etapa": "extrajudicial"})
    assert r.status_code == 400
    with psycopg2.connect(URL_TEST) as c, c.cursor() as cur:
        with pytest.raises(psycopg2.Error):
            cur.execute("UPDATE cobranzas SET etapa = 'extrajudicial' WHERE id = %s", (cob,))

    # El mismo rol en el mismo tribunal no se repite.
    tercera = _otra_cobranza(cliente_http, h, cartera, externo="EXT-C")
    assert _demanda(cliente_http, h, [tercera]).status_code == 400


def test_demanda_solo_con_cobranzas_del_mismo_deudor(cliente_http, org_a):
    h = login(cliente_http, org_a["email"])
    a = crear_cartera(cliente_http, h, n=211)
    b = crear_cartera(cliente_http, h, n=212)
    r = _demanda(cliente_http, h, [a["cobranza_id"], b["cobranza_id"]], rol=None)
    assert r.status_code == 400
    assert "mismo deudor" in r.json()["detail"]
    # Nada quedó a medias.
    assert _ciclo(cliente_http, h, a["cobranza_id"])["etapa"] == "ingreso"


def test_tramites_plazos_embargo_y_termino(cliente_http, org_a):
    h = login(cliente_http, org_a["email"])
    cartera = crear_cartera(cliente_http, h, monto=800_000, n=221)
    causa = _demanda(cliente_http, h, [cartera["cobranza_id"]], rol="C-77-2026",
                     fecha_ingreso=(hoy_chile() - timedelta(days=20)).isoformat()).json()
    hoy = hoy_chile()

    # Notificado hace 10 días: el plazo de seguimiento vence hoy y va con su gasto.
    notif = _tipo(cliente_http, h, "notificado_requerido")
    r = cliente_http.post(f"/api/judicial/causas/{causa['id']}/tramites", headers=h, json={
        "tipo_id": notif["id"], "fecha": (hoy - timedelta(days=10)).isoformat(),
        "descripcion": "Receptor notifica en el domicilio",
        "gasto": {"monto": 35000, "proveedor": "Receptor judicial", "numero_boleta": "B-15"}})
    assert r.status_code == 201, r.text
    registrado = r.json()
    assert registrado["etapa_procesal"] == "notificacion"
    assert registrado["tramite"]["plazo_fecha"] == hoy.isoformat()
    assert registrado["gasto_id"]

    # Una observación no cumple el plazo.
    r = cliente_http.post(f"/api/judicial/causas/{causa['id']}/tramites", headers=h,
                          json={"descripcion": "Se revisa el expediente"})
    assert r.status_code == 201
    ficha = cliente_http.get(f"/api/judicial/causas/{causa['id']}", headers=h).json()
    assert ficha["plazo_fecha"] == hoy.isoformat()
    assert ficha["siguiente_nombre"] == "Certificado: no opuso excepciones"
    assert float(ficha["total_gastos"]) == 35000
    assert _ciclo(cliente_http, h, cartera["cobranza_id"])["paso_actual"] == "notificacion"

    # El plazo aparece en la agenda de hoy y en la bandeja.
    agenda = cliente_http.get("/api/agenda/hoy", headers=h).json()
    assert any(i["tipo"] == "plazo" and i["causa_id"] == causa["id"] for i in agenda)
    resumen = cliente_http.get("/api/judicial/resumen", headers=h).json()
    assert resumen["plazos_hoy"] >= 1 and resumen["por_etapa"]["notificacion"] >= 1
    filas = cliente_http.get("/api/judicial/causas", params={"q": "C-77"}, headers=h).json()
    assert [f["id"] for f in filas] == [causa["id"]]
    assert filas[0]["ultimo_tramite"] == "Notificado y requerido de pago"

    # Embargo de un vehículo; después se remata.
    r = cliente_http.post(f"/api/judicial/causas/{causa['id']}/embargos", headers=h, json={
        "tipo_bien": "vehiculo", "descripcion": "Automóvil patente ABCD-12", "fecha_traba": hoy.isoformat()})
    assert r.status_code == 201, r.text
    r = cliente_http.put(f"/api/judicial/embargos/{r.json()['id']}", headers=h,
                         json={"estado": "rematado", "monto_remate": 2_500_000})
    assert r.status_code == 200 and r.json()["estado"] == "rematado"

    # Un trámite de término propone cerrar; al cerrar, la cobranza queda pagada.
    pago = _tipo(cliente_http, h, "da_cuenta_pago")
    r = cliente_http.post(f"/api/judicial/causas/{causa['id']}/tramites", headers=h, json={"tipo_id": pago["id"]})
    assert r.json()["propone_resultado"] == "pagada"
    r = cliente_http.post(f"/api/judicial/causas/{causa['id']}/terminar", headers=h, json={"resultado": "pagada"})
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "terminada" and r.json()["plazo_fecha"] is None
    ciclo = _ciclo(cliente_http, h, cartera["cobranza_id"])
    assert ciclo["estado"] == "pagada" and ciclo["motivo_cierre"] == "pagada"
    estados = {p["clave"]: p["estado"] for p in ciclo["pasos"]}
    assert estados["termino"] == "actual" and estados["notificacion"] == "hecho"
    assert estados["remate"] == "omitido"
    # Causa terminada: no admite más trámites.
    r = cliente_http.post(f"/api/judicial/causas/{causa['id']}/tramites", headers=h, json={"descripcion": "x"})
    assert r.status_code == 400

    # Los trámites no se editan ni como dueño de las tablas.
    with psycopg2.connect(URL_TEST) as c, c.cursor() as cur:
        with pytest.raises(psycopg2.Error):
            cur.execute("UPDATE tramites SET descripcion = 'otra' WHERE causa_id = %s", (causa["id"],))


def test_gastos_rendicion_y_reembolso(cliente_http, org_a):
    h = login(cliente_http, org_a["email"])
    a = crear_cartera(cliente_http, h, n=231)
    b = crear_cartera(cliente_http, h, n=232)
    causa = _demanda(cliente_http, h, [a["cobranza_id"]], rol="C-5-2026").json()

    def gasto(**datos):
        r = cliente_http.post("/api/gastos/", headers=h, json={"tipo": "receptor", **datos})
        assert r.status_code == 201, r.text
        return r.json()

    g1 = gasto(causa_id=causa["id"], concepto="Búsqueda negativa", monto=20000)
    g2 = gasto(causa_id=causa["id"], concepto="Notificación art. 44", monto=30000)
    g3 = gasto(cobranza_id=b["cobranza_id"], tipo="correo", concepto="Carta certificada", monto=4000)
    assert g1["cliente_id"] == a["cliente_id"] and g3["cliente_id"] == b["cliente_id"]

    resumen = {f["cliente_id"]: f for f in cliente_http.get("/api/gastos/resumen", headers=h).json()}
    assert float(resumen[a["cliente_id"]]["por_rendir"]) == 50000
    assert resumen[a["cliente_id"]]["cantidad_por_rendir"] == 2

    # Una rendición es de un solo cliente.
    r = cliente_http.post("/api/gastos/rendiciones", headers=h, json={"gasto_ids": [g1["id"], g3["id"]]})
    assert r.status_code == 400
    r = cliente_http.post("/api/gastos/rendiciones", headers=h, json={"gasto_ids": [g1["id"], g2["id"]]})
    assert r.status_code == 201, r.text
    rendicion = r.json()
    assert rendicion["numero"] == 1 and float(rendicion["total"]) == 50000 and rendicion["cantidad"] == 2
    # Rendido no se corrige.
    assert cliente_http.put(f"/api/gastos/{g1['id']}", headers=h, json={"monto": 1}).status_code == 400

    r = cliente_http.post(f"/api/gastos/rendiciones/{rendicion['id']}/pagada", headers=h, json={})
    assert r.status_code == 200
    assert {g["estado"] for g in r.json()["gastos"]} == {"reembolsado"}

    # Devolución masiva sin rendición.
    r = cliente_http.post("/api/gastos/reembolsar", headers=h, json={"gasto_ids": [g3["id"]]})
    assert r.status_code == 200 and r.json()[0]["estado"] == "reembolsado"
    resumen = {f["cliente_id"]: f for f in cliente_http.get("/api/gastos/resumen", headers=h).json()}
    assert float(resumen[a["cliente_id"]]["total_adeudado"]) == 0
    assert float(resumen[b["cliente_id"]]["reembolsado"]) == 4000


def test_sugeridas_por_regla_del_cliente(cliente_http, org_a):
    h = login(cliente_http, org_a["email"])
    cartera = crear_cartera(cliente_http, h, n=241)
    sugeridas = cliente_http.get("/api/judicial/para-demanda", headers=h).json()["sugeridas"]
    assert cartera["cobranza_id"] not in [s["id"] for s in sugeridas]
    # Cliente que pasa altiro a judicial.
    r = cliente_http.put(f"/api/clientes/{cartera['cliente_id']}", headers=h, json={"dias_para_demanda": 0})
    assert r.status_code == 200, r.text
    sugeridas = cliente_http.get("/api/judicial/para-demanda", headers=h).json()["sugeridas"]
    assert cartera["cobranza_id"] in [s["id"] for s in sugeridas]


def test_catalogo_de_tramites_propio(cliente_http, org_a, org_b):
    ha = login(cliente_http, org_a["email"])
    hb = login(cliente_http, org_b["email"])
    sistema = _tipo(cliente_http, ha, "sentencia")
    assert cliente_http.put(f"/api/judicial/tipos-tramite/{sistema['id']}", headers=ha,
                            json={"plazo_dias": 1}).status_code == 403
    r = cliente_http.post("/api/judicial/tipos-tramite", headers=ha, json={
        "nombre": "Revisión mensual del expediente", "plazo_dias": 30, "etapa": "defensa"})
    assert r.status_code == 201 and r.json()["propio"] is True
    propio = r.json()["id"]
    assert cliente_http.put(f"/api/judicial/tipos-tramite/{propio}", headers=ha,
                            json={"plazo_dias": 15}).json()["plazo_dias"] == 15
    # La otra organización no lo ve.
    assert propio not in [t["id"] for t in cliente_http.get("/api/judicial/tipos-tramite", headers=hb).json()]


def test_judicial_aislado_y_por_plan(cliente_http, org_a, org_b):
    ha = login(cliente_http, org_a["email"])
    hb = login(cliente_http, org_b["email"])
    cartera = crear_cartera(cliente_http, ha, n=251)
    causa = _demanda(cliente_http, ha, [cartera["cobranza_id"]], rol="C-9-2026").json()
    assert cliente_http.get(f"/api/judicial/causas/{causa['id']}", headers=hb).status_code == 404
    assert cliente_http.get("/api/judicial/causas", headers=hb).json() == []

    base = crear_organizacion(plan="base")
    hbase = login(cliente_http, base["email"])
    assert cliente_http.get("/api/judicial/causas", headers=hbase).status_code == 402
    assert cliente_http.get("/api/gastos/", headers=hbase).status_code == 402
    # El ciclo de vida es para todos los planes.
    propia = crear_cartera(cliente_http, hbase, n=252)
    assert _ciclo(cliente_http, hbase, propia["cobranza_id"])["paso_actual"] == "ingreso"


def test_cerrar_a_mano_deja_motivo_y_fecha(cliente_http, org_a):
    h = login(cliente_http, org_a["email"])
    cartera = crear_cartera(cliente_http, h, n=261)
    r = cliente_http.put(f"/api/cobranzas/{cartera['cobranza_id']}", headers=h,
                         json={"estado": "castigo", "motivo_cierre": "inubicable"})
    assert r.status_code == 200, r.text
    assert r.json()["motivo_cierre"] == "inubicable" and r.json()["fecha_cierre"] == hoy_chile().isoformat()
    ciclo = _ciclo(cliente_http, h, cartera["cobranza_id"])
    assert ciclo["paso_actual"] == "termino" and ciclo["motivo_cierre_nombre"] == "Deudor inubicable"
    # Reabrir limpia el cierre.
    r = cliente_http.put(f"/api/cobranzas/{cartera['cobranza_id']}", headers=h, json={"estado": "activa"})
    assert r.json()["motivo_cierre"] is None and r.json()["fecha_cierre"] is None




def test_historial_de_pagos_del_deudor_y_resumen_por_etapa(cliente_http, org_a):
    h = login(cliente_http, org_a["email"])
    cartera = crear_cartera(cliente_http, h, monto=300_000, n=271)
    otra = _otra_cobranza(cliente_http, h, cartera, monto=100_000, externo="EXT-P")
    for cob, monto in ((cartera["cobranza_id"], 50_000), (otra, 100_000)):
        r = cliente_http.post("/api/pagos/", headers=h, json={
            "cobranza_id": cob, "monto": monto, "capital": monto, "forma_pago": "transferencia",
            "estado_pago": "abono"})
        assert r.status_code == 201, r.text
    pagos = cliente_http.get("/api/pagos/", params={"deudor_id": cartera["deudor_id"]}, headers=h).json()
    assert len({p["numero_cobranza"] for p in pagos}) == 2 and cartera["numero"] in {p["numero_cobranza"] for p in pagos}
    assert {float(p["monto"]) for p in pagos} == {50_000, 100_000}
    assert all(p["usuario_nombre"] for p in pagos)

    # La que quedó en cero se cierra como pagada y cuenta en "término".
    ciclo = _ciclo(cliente_http, h, otra)
    assert ciclo["paso_actual"] == "termino" and ciclo["motivo_cierre"] == "pagada"
    resumen = {f["etapa"]: f for f in cliente_http.get("/api/cobranzas/resumen-etapas", headers=h).json()}
    # El pago deja una gestión: la otra cobranza pasó sola a extrajudicial.
    assert resumen["termino"]["cantidad"] >= 1 and resumen["extrajudicial"]["cantidad"] >= 1
    terminadas = cliente_http.get("/api/cobranzas/", params={"etapa": "termino"}, headers=h).json()
    assert otra in [c["id"] for c in terminadas]
    caras = cliente_http.get("/api/cobranzas/", params={"saldo_min": 200_000}, headers=h).json()
    assert cartera["cobranza_id"] in [c["id"] for c in caras] and otra not in [c["id"] for c in caras]


def test_simulador_genera_cartera_coherente():
    """El simulador a escala chica: inserta todo respetando las reglas de la base."""
    from app.database import engine
    from app.simulador import simular

    conexion = engine.raw_connection()
    try:
        r = simular(conexion, anios=2, escala=0.05, semilla=3, password="Clave-Simulacion-2026", informar=lambda *_: None)
    finally:
        conexion.close()
    assert r["cobranzas"] == 95 and r["gestiones"] > 300 and r["causas"] > 10 and r["tramites"] > r["causas"]
    with psycopg2.connect(URL_TEST) as c, c.cursor() as cur:
        cur.execute("""SELECT count(*) FROM cobranzas c JOIN organizaciones o ON o.id = c.organizacion_id
                       WHERE o.slug = 'simulacion' AND c.estado = 'pagada' AND c.monto_actual > 0""")
        assert cur.fetchone()[0] == 0
        cur.execute("""SELECT count(*) FROM causas ca JOIN organizaciones o ON o.id = ca.organizacion_id
                       WHERE o.slug = 'simulacion' AND NOT EXISTS (SELECT 1 FROM causa_cobranzas cc WHERE cc.causa_id = ca.id)""")
        assert cur.fetchone()[0] == 0

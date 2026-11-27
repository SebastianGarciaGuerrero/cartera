"""
Operación con cartera real: carga masiva flexible (varias hojas, títulos en
otra fila, terceros, actualización), gestiones masivas con tipo, asignación
y eliminación de cartera, anulación de pagos, acuerdos para dar de baja,
agenda por secciones y paso a producción.
"""

from datetime import date, timedelta
from io import BytesIO

from openpyxl import Workbook
from sqlalchemy import text

from app.indicadores import hoy_chile
from app.operaciones import sumar_meses
from tests.conftest import agregar_usuario, crear_cartera, crear_organizacion, login, rut_valido
from tests.test_negocio import cargar

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

TITULOS = ["Filial", "ID", "Rut Paciente", "Nombre Paciente", "Saldo Capital", "Teléfono 1 paciente",
           "Rut Deudor", "Nombre Deudor", "Dirección Deudor", "Mail Deudor", "Telefono Deudor 1",
           "Telefono Deudor 2", "N° Pagaré", "Dicom", "Previsión", "Etapas de cobranza"]


def _libro(hojas: dict) -> bytes:
    """{nombre de hoja: filas}; la fila 1 de cada hoja es de grupos (como la planilla de la clínica)."""
    wb = Workbook()
    wb.remove(wb.active)
    for nombre, filas in hojas.items():
        ws = wb.create_sheet(nombre)
        if nombre != "Otra":  # "Otra": una hoja cualquiera, sin la planilla
            ws.append(["Clínica (HIS)"] * 4 + [None] * (len(TITULOS) - 4))
            ws.append(TITULOS)
        for f in filas:
            ws.append(f)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _fila(filial, id_cuenta, n, monto=300000, estado="Pre-judicial", tel_deudor=912345678, paciente=None):
    rut = rut_valido(n)
    return [filial, id_cuenta, paciente or rut, "Paciente " + str(n), monto, 56987654321,
            rut, f"Deudor {n}", "Calle 1", f"d{n}@correo.cl", tel_deudor, None, 123456789012,
            "SI", "FONASA", estado]


def _cliente(cliente_http, h, n):
    return cliente_http.post("/api/clientes/", headers=h,
                             json={"rut": rut_valido(n), "razon_social": f"Red {n} SpA"}).json()["id"]


def test_carga_planilla_de_la_clinica_y_actualizacion(cliente_http, org_a):
    h = login(cliente_http, org_a["email"])
    cliente = _cliente(cliente_http, h, 500)
    contenido = _libro({
        "Santiago": [_fila("SANTIAGO", "1001-1", 501), _fila("SANTIAGO", "1002-2", 502, estado="Deuda saldada"),
                     _fila("SANTIAGO", "1003-3", 503, paciente=rut_valido(599)),
                     ["SANTIAGO", "1004-4", None, None, 1000, None, "12345678-9", "RUT malo"]],
        "Providencia": [_fila("Providencia", "1001-1", 504),  # mismo ID que en Santiago: otra filial
                        _fila("Providencia", "1005-5", 505, estado="Eliminada de cartera judicial")],
        "Otra": [["sin", "columnas"]],
    })
    vista = cliente_http.post("/api/importar/analizar", headers=h,
                              files={"archivo": ("p.xlsx", contenido, XLSX)}).json()["hojas"]
    assert [(v["nombre"], v["fila_titulos"], v["sirve"]) for v in vista] == [
        ("Santiago", 2, True), ("Providencia", 2, True), ("Otra", 1, False)]

    res = cargar(cliente_http, h, "/api/importar/cobranzas", contenido,
                 {"cliente_id": cliente, "columnas_extra": '["Previsión"]'})
    assert res["cobranzas_creadas"] == 5 and res["total_errores"] == 1
    assert res["filiales_creadas"] == ["Santiago", "Providencia"] and res["campos_creados"] == ["Previsión"]

    cobs = {c["id_externo"] + "/" + c["filial_nombre"]: c for c in
            cliente_http.get("/api/cobranzas/", params={"cliente_id": cliente}, headers=h).json()}
    assert set(cobs) == {"1001-1/Santiago", "1002-2/Santiago", "1003-3/Santiago", "1001-1/Providencia",
                         "1005-5/Providencia"}
    assert cobs["1002-2/Santiago"]["estado"] == "pagada" and float(cobs["1002-2/Santiago"]["monto_actual"]) == 0
    assert cobs["1005-5/Providencia"]["estado"] == "eliminada"
    ficha = cliente_http.get(f"/api/cobranzas/{cobs['1003-3/Santiago']['id']}", headers=h).json()
    assert ficha["numero_documento"] == "123456789012" and ficha["datos_extra"] == {"prevision": "FONASA"}
    assert [t["rol"] for t in ficha["terceros"]] == ["paciente"]
    deudor = cliente_http.get(f"/api/deudores/{ficha['deudor_id']}", headers=h).json()
    valores = {c["valor"] for c in deudor["contactos"]}
    assert "+56 9 1234 5678" in valores and "d503@correo.cl" in valores and deudor["en_boletin_comercial"]
    # El paciente es otra persona: su teléfono es suyo, no del deudor.
    assert "+56 9 8765 4321" not in valores
    # Paciente = deudor: sus contactos van al deudor.
    otro = cliente_http.get(f"/api/cobranzas/{cobs['1001-1/Santiago']['id']}", headers=h).json()
    contactos = cliente_http.get(f"/api/deudores/{otro['deudor_id']}", headers=h).json()["contactos"]
    assert "+56 9 8765 4321" in {c["valor"] for c in contactos}

    # Subir lo mismo de nuevo no duplica nada.
    res = cargar(cliente_http, h, "/api/importar/cobranzas", contenido, {"cliente_id": cliente})
    assert res["cobranzas_creadas"] == 0 and res["ya_existian"] == 5

    # Actualizar (solo admin): teléfono nuevo y monto distinto en una cobranza sin pagos.
    nuevo = _libro({"Santiago": [_fila("SANTIAGO", "1001-1", 501, monto=310000, tel_deudor=998887766)]})
    supervisor = login(cliente_http, agregar_usuario(org_a["org_id"], "supervisor"))
    r = cliente_http.post("/api/importar/cobranzas", headers=supervisor,
                          data={"cliente_id": cliente, "actualizar": "true"},
                          files={"archivo": ("p.xlsx", nuevo, XLSX)})
    assert r.status_code == 403
    res = cargar(cliente_http, h, "/api/importar/cobranzas", nuevo, {"cliente_id": cliente, "actualizar": "true"})
    assert res["cobranzas_actualizadas"] == 1
    cob = cliente_http.get(f"/api/cobranzas/{cobs['1001-1/Santiago']['id']}", headers=h).json()
    assert float(cob["monto_original"]) == 310000
    gestion = cliente_http.get("/api/gestiones/", params={"cobranza_id": cob["id"]}, headers=h).json()[0]
    assert gestion["descripcion"].startswith("DATOS ACTUALIZADOS POR CARGA MASIVA")
    assert "+56 9 9888 7766" in gestion["descripcion"]


def test_gestiones_masivas_con_tipo_rut_y_numero(cliente_http, org_a):
    h = login(cliente_http, org_a["email"])
    cartera = crear_cartera(cliente_http, h, n=510)
    wb = Workbook()
    ws = wb.active
    ws.append(["RUT deudor", "N° cobranza", "Tipo", "Gestión", "Próximo contacto"])
    manana = (hoy_chile() + timedelta(days=1)).strftime("%d-%m-%Y")
    ws.append([rut_valido(1510), None, "No contesta", None, None])
    ws.append([None, cartera["numero"], "whatsapp", "Se envía recordatorio", manana])
    ws.append([None, 99999999, "Llamada", "x", None])
    ws.append([rut_valido(1510), None, "Tipo inventado", "x", None])
    buf = BytesIO()
    wb.save(buf)
    res = cargar(cliente_http, h, "/api/importar/gestiones", buf.getvalue())
    assert res["gestiones_creadas"] == 2 and [e["fila"] for e in res["errores"]] == [4, 5]
    tipos = {t["id"]: t["codigo"] for t in cliente_http.get("/api/gestiones/tipos", headers=h).json()}
    historial = cliente_http.get("/api/gestiones/", params={"cobranza_id": cartera["cobranza_id"]}, headers=h).json()
    assert sorted(tipos[g["tipo_id"]] for g in historial if g["es_masivo"]) == ["no_contesta", "whatsapp"]
    assert any(g["fecha_proximo_contacto"] for g in historial)

    # Las dos filas con error vuelven en el Excel para corregir, con la casilla mala en amarillo.
    trabajos = cliente_http.post("/api/importar/gestiones", headers=h,
                                 files={"archivo": ("g.xlsx", buf.getvalue(), XLSX)}).json()
    xlsx = cliente_http.get(f"/api/importar/trabajos/{trabajos['trabajo_id']}/errores", headers=h)
    assert xlsx.status_code == 200
    from openpyxl import load_workbook
    hoja = load_workbook(BytesIO(xlsx.content)).active
    assert hoja.max_row == 3 and hoja.cell(1, 6).value == "Motivo del error"
    amarillas = [(c.row, c.column) for fila in hoja.iter_rows(min_row=2) for c in fila
                 if c.fill.fgColor.rgb in ("00FFEB3B", "FFFFEB3B")]
    assert amarillas == [(2, 2), (3, 3)]  # el N° que no existe y el tipo inventado


def test_asignar_repartir_y_eliminar_de_cartera(cliente_http, org_a):
    h = login(cliente_http, org_a["email"])
    ana = agregar_usuario(org_a["org_id"], "operador")
    beto = agregar_usuario(org_a["org_id"], "operador")
    usuarios = {u["email"]: u["id"] for u in cliente_http.get("/api/usuarios/", headers=h).json()}
    cliente = _cliente(cliente_http, h, 520)
    ids = []
    for n in range(4):
        deudor = cliente_http.post("/api/deudores/", headers=h,
                                   json={"rut": rut_valido(521 + n), "nombre": f"D {n}"}).json()["id"]
        ids.append(cliente_http.post("/api/cobranzas/", headers=h, json={
            "cliente_id": cliente, "deudor_id": deudor, "monto_original": 1000}).json()["id"])

    r = cliente_http.post("/api/cartera/asignar", headers=h, json={
        "filtro": {"cliente_id": cliente, "sin_ejecutivo": True},
        "ejecutivo_ids": [usuarios[ana], usuarios[beto]]})
    assert r.status_code == 200, r.text
    assert r.json()["cambiadas"] == 4 and sorted(r.json()["por_ejecutivo"].values()) == [2, 2]
    sin = cliente_http.get("/api/cobranzas/", params={"cliente_id": cliente, "sin_ejecutivo": True}, headers=h)
    assert sin.json() == []
    lista = cliente_http.get("/api/cobranzas/", params={"cliente_id": cliente}, headers=h).json()
    assert {c["ejecutivo_nombre"] for c in lista} == {u["nombre"] for u in cliente_http.get(
        "/api/usuarios/", headers=h).json() if u["email"] in (ana, beto)}

    # Un ejecutivo (operador) no puede asignar ni eliminar cartera.
    ho = login(cliente_http, ana)
    assert cliente_http.post("/api/cartera/asignar", headers=ho, json={"cobranza_ids": ids[:1]}).status_code == 403

    r = cliente_http.post("/api/cartera/eliminar", headers=h,
                          json={"cobranza_ids": ids[:2], "motivo": "El cliente informa que la deuda no corresponde"})
    assert r.json()["cambiadas"] == 2
    cob = cliente_http.get(f"/api/cobranzas/{ids[0]}", headers=h).json()
    assert cob["estado"] == "eliminada" and cob["motivo_cierre"] == "eliminada_cartera"
    historial = cliente_http.get("/api/gestiones/", params={"cobranza_id": ids[0]}, headers=h).json()
    assert historial[0]["descripcion"].startswith("ELIMINADA DE CARTERA")
    # Ya no es cartera asignada en el panel, y una cerrada no se vuelve a eliminar.
    panel = cliente_http.get("/api/panel", params={"cliente_id": cliente}, headers=h).json()
    assert float(panel["por_cliente"][0]["asignado"]) == 2000
    assert cliente_http.post("/api/cartera/eliminar", headers=h,
                             json={"cobranza_ids": ids[:1], "motivo": "otra vez"}).json()["cambiadas"] == 0


def test_anular_pago_revierte_todo_y_conserva_el_historial(cliente_http, org_a):
    h = login(cliente_http, org_a["email"])
    cartera = crear_cartera(cliente_http, h, monto=100_000, n=530)
    acuerdo = cliente_http.post("/api/acuerdos/", headers=h, json={
        "cobranza_id": cartera["cobranza_id"], "monto_total_acordado": 100000, "numero_cuotas": 1,
        "fecha_primera_cuota": hoy_chile().isoformat()}).json()
    cuota = next(c for c in acuerdo["cuotas"] if c["numero_cuota"] == 1)
    pago = cliente_http.post("/api/pagos/", headers=h, json={
        "cobranza_id": cartera["cobranza_id"], "cuota_id": cuota["id"], "monto": 100000, "capital": 100000}).json()
    assert cliente_http.get(f"/api/cobranzas/{cartera['cobranza_id']}", headers=h).json()["estado"] == "pagada"

    ho = login(cliente_http, agregar_usuario(org_a["org_id"], "operador"))
    assert cliente_http.post(f"/api/pagos/{pago['id']}/anular", headers=ho,
                             json={"motivo": "mal ingresado"}).status_code == 403
    r = cliente_http.post(f"/api/pagos/{pago['id']}/anular", headers=h,
                          json={"motivo": "Se ingresó en la cobranza equivocada"})
    assert r.status_code == 200, r.text
    assert r.json()["anulado_at"] and r.json()["motivo_anulacion"].startswith("Se ingresó")

    cob = cliente_http.get(f"/api/cobranzas/{cartera['cobranza_id']}", headers=h).json()
    assert cob["estado"] == "acuerdo_pago" and float(cob["monto_actual"]) == 100000 and cob["fecha_cierre"] is None
    detalle = cliente_http.get(f"/api/acuerdos/{acuerdo['id']}", headers=h).json()
    assert detalle["estado"] == "vigente"
    assert next(c for c in detalle["cuotas"] if c["numero_cuota"] == 1)["estado"] == "pendiente"
    textos = [g["descripcion"] for g in
              cliente_http.get("/api/gestiones/", params={"cobranza_id": cartera["cobranza_id"]}, headers=h).json()]
    assert textos[0].startswith("PAGO ANULADO") and any(t.startswith("Pago de cuota 1") for t in textos)
    # Fuera de los totales, y no se anula dos veces ni se edita.
    panel = cliente_http.get("/api/panel", headers=h).json()
    assert cliente_http.post(f"/api/pagos/{pago['id']}/anular", headers=h,
                             json={"motivo": "de nuevo"}).status_code == 400
    assert isinstance(panel["recupero"]["pagos"], int)
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        db.execute(text("UPDATE pagos SET monto = 1 WHERE id = :id"), {"id": pago["id"]})
        raise AssertionError("la base dejó editar un pago")
    except Exception as e:
        assert "inmutables" in str(e)
    finally:
        db.rollback()
        db.close()


def test_acuerdo_sin_pagos_tres_meses_sale_para_baja(cliente_http, org_a):
    h = login(cliente_http, org_a["email"])
    cartera = crear_cartera(cliente_http, h, monto=90_000, n=540)
    hoy = hoy_chile()
    acuerdo = cliente_http.post("/api/acuerdos/", headers=h, json={
        "cobranza_id": cartera["cobranza_id"], "monto_total_acordado": 90000, "numero_cuotas": 6,
        "fecha_primera_cuota": (sumar_meses(hoy, -4)).isoformat()}).json()
    avisos = cliente_http.get("/api/agenda/avisos", headers=h).json()
    baja = [i for i in avisos["hoy"] if i["tipo"] == "baja"]
    assert len(baja) == 1 and baja[0]["acuerdo_id"] == acuerdo["id"] and baja[0]["seccion"] == "bajas"
    assert any(i["seccion"] == "cuotas_vencidas" for i in avisos["atrasados"])

    r = cliente_http.post(f"/api/acuerdos/{acuerdo['id']}/baja", headers=h, json={"motivo": "No responde"})
    assert r.status_code == 200 and r.json()["estado"] == "incumplido"
    assert cliente_http.get(f"/api/cobranzas/{cartera['cobranza_id']}", headers=h).json()["estado"] == "activa"
    avisos = cliente_http.get("/api/agenda/avisos", headers=h).json()
    assert not [i for i in avisos["hoy"] + avisos["atrasados"] if i["cobranza_id"] == cartera["cobranza_id"]]


def test_recordatorios_por_seccion(cliente_http, org_a):
    h = login(cliente_http, org_a["email"])
    hoy = hoy_chile().isoformat()
    for tipo in ("llamada", "whatsapp", "correo"):
        assert cliente_http.post("/api/recordatorios", headers=h, json={
            "fecha": hoy, "titulo": f"Recordatorio {tipo}", "tipo": tipo}).status_code == 201
    items = cliente_http.get("/api/agenda/hoy", headers=h).json()
    secciones = {i["titulo"]: i["seccion"] for i in items if i["tipo"] == "recordatorio"}
    assert secciones == {"Recordatorio llamada": "llamadas", "Recordatorio whatsapp": "whatsapp",
                         "Recordatorio correo": "correos"}


def test_pasar_a_produccion(cliente_http):
    org = crear_organizacion()
    h = login(cliente_http, org["email"])
    cartera = crear_cartera(cliente_http, h, n=550)
    cliente_http.post("/api/gestiones/", headers=h, json={"cobranza_id": cartera["cobranza_id"], "descripcion": "x"})
    cliente_http.post("/api/pagos/", headers=h, json={"cobranza_id": cartera["cobranza_id"], "monto": 10, "capital": 10})
    con_portal = _cliente(cliente_http, h, 551)
    agregar_usuario(org["org_id"], "mandante", cliente_id=con_portal)
    otra = crear_organizacion()
    ho = login(cliente_http, otra["email"])
    ajena = crear_cartera(cliente_http, ho, n=552)

    estado = cliente_http.get("/api/organizacion/produccion", headers=h).json()
    assert estado["en_produccion"] is None and estado["datos_de_prueba"]["cobranzas"] == 1
    nombre = cliente_http.get("/api/organizacion", headers=h).json()["nombre"]
    assert cliente_http.post("/api/organizacion/produccion", headers=h,
                             json={"confirmacion": "otro nombre"}).status_code == 422
    # Corre en segundo plano (como las cargas): responde con el trabajo y su avance.
    r = cliente_http.post("/api/organizacion/produccion", headers=h, json={"confirmacion": nombre})
    assert r.status_code == 202, r.text
    trabajo = cliente_http.get(f"/api/importar/trabajos/{r.json()['trabajo_id']}", headers=h).json()
    assert trabajo["estado"] == "terminado" and trabajo["procesadas"] == trabajo["total"] > 3, trabajo
    assert trabajo["resultado"]["borrado"]["cobranzas"] == 1
    estado = cliente_http.get("/api/organizacion/produccion", headers=h).json()
    assert estado["en_produccion"] and estado["numero_siguiente"] == 40000 and estado["en_curso"] is None
    assert estado["datos_de_prueba"] == {"cobranzas": 0, "deudores": 0, "gestiones": 0, "pagos": 0,
                                         "acuerdos_pago": 0, "causas": 0, "clientes": 1}
    assert cliente_http.post("/api/organizacion/produccion", headers=h,
                             json={"confirmacion": nombre}).status_code == 409

    nueva = crear_cartera(cliente_http, h, n=553)
    assert nueva["numero"] == 40000
    # La otra organización no se tocó, y las gestiones siguen siendo inmutables.
    assert cliente_http.get(f"/api/cobranzas/{ajena['cobranza_id']}", headers=ho).status_code == 200
    from app.database import SessionLocal
    cliente_http.post("/api/gestiones/", headers=ho, json={"cobranza_id": ajena["cobranza_id"], "descripcion": "y"})
    db = SessionLocal()
    try:
        db.execute(text("UPDATE gestiones SET descripcion = 'x' WHERE cobranza_id = :c"),
                   {"c": ajena["cobranza_id"]})
        raise AssertionError("la base dejó editar una gestión: la protección quedó apagada")
    except Exception as e:
        assert "inmutables" in str(e)
    finally:
        db.rollback()
        db.close()


def test_fecha_y_tipo_de_columna_extra():
    from app.carga_masiva import _tipo_campo, estado_desde_texto, reconocer, telefono
    assert _tipo_campo("Fecha Alta", [date(2026, 1, 1)] * 5) == "fecha"
    assert _tipo_campo("Honorarios", [1.5, 2]) == "monto"
    assert estado_desde_texto("Deudor fallecido") == ("archivada", "fallecido")
    assert reconocer("Correo electrónico paciente")[:2] == ("t_email", "paciente")
    assert telefono(56912345678)[1] == "+56 9 1234 5678" and telefono("22") is None


def test_tipos_de_gestion_con_los_usos_de_cada_persona(cliente_http, org_a):
    """La ficha muestra primero los tipos que más usa quien registra (no cuentan los de otros)."""
    h = login(cliente_http, org_a["email"])
    cartera = crear_cartera(cliente_http, h, n=560)
    tipos = {t["codigo"]: t["id"] for t in cliente_http.get("/api/gestiones/tipos", headers=h).json()}
    for codigo in ("llamada", "llamada", "whatsapp"):
        r = cliente_http.post("/api/gestiones/", headers=h, json={
            "cobranza_id": cartera["cobranza_id"], "tipo_id": tipos[codigo], "descripcion": "Gestión de prueba"})
        assert r.status_code == 201, r.text
    ho = login(cliente_http, agregar_usuario(org_a["org_id"], "operador"))
    cliente_http.post("/api/gestiones/", headers=ho, json={
        "cobranza_id": cartera["cobranza_id"], "tipo_id": tipos["email"], "descripcion": "Correo enviado"})

    usos = {t["codigo"]: t["usos"] for t in cliente_http.get("/api/gestiones/tipos", headers=h).json()}
    assert usos["llamada"] == 2 and usos["whatsapp"] == 1 and usos["email"] == 0
    usos_otro = {t["codigo"]: t["usos"] for t in cliente_http.get("/api/gestiones/tipos", headers=ho).json()}
    assert usos_otro["email"] == 1 and usos_otro["llamada"] == 0


def test_paciente_de_respaldo_y_excel_para_corregir(cliente_http, org_a):
    """Sin RUT o nombre del deudor se usa el paciente; lo que no entra vuelve en un Excel con lo faltante en amarillo."""
    from openpyxl import load_workbook

    h = login(cliente_http, org_a["email"])
    cliente = _cliente(cliente_http, h, 570)
    sin_deudor = _fila("SANTIAGO", "2001-1", 571, paciente=rut_valido(571))
    sin_deudor[6], sin_deudor[7] = None, None                       # sin RUT ni nombre del deudor
    sin_nombre = _fila("SANTIAGO", "2002-2", 572)                    # RUT deudor = RUT paciente
    sin_nombre[7] = None
    otro_sin_nombre = _fila("SANTIAGO", "2003-3", 573, paciente=rut_valido(574))
    otro_sin_nombre[7] = None                                        # el deudor es otra persona: no se adivina
    sin_saldo = _fila("SANTIAGO", "2004-4", 575, monto=None)
    rut_malo = _fila("SANTIAGO", "2005-5", 576)
    rut_malo[6] = "12345678-9"
    contenido = _libro({"Santiago": [sin_deudor, sin_nombre, otro_sin_nombre, sin_saldo, rut_malo]})

    r = cliente_http.post("/api/importar/cobranzas", headers=h, data={"cliente_id": cliente},
                          files={"archivo": ("filial.xlsx", contenido, XLSX)})
    trabajo_id = r.json()["trabajo_id"]
    trabajo = cliente_http.get(f"/api/importar/trabajos/{trabajo_id}", headers=h).json()
    res = trabajo["resultado"]
    assert res["cobranzas_creadas"] == 2 and res["total_errores"] == 3
    assert res["excel_errores"] is True and "correccion" not in res
    assert any("se tomó al paciente" in a for a in res["avisos"])

    cobs = {c["id_externo"]: c for c in cliente_http.get("/api/cobranzas/", params={"cliente_id": cliente},
                                                          headers=h).json()}
    deudor = cliente_http.get(f"/api/deudores/{cobs['2001-1']['deudor_id']}", headers=h).json()
    assert deudor["nombre"] == "Paciente 571"
    deudor = cliente_http.get(f"/api/deudores/{cobs['2002-2']['deudor_id']}", headers=h).json()
    assert deudor["nombre"] == "Paciente 572"

    # El Excel para corregir: misma hoja y títulos, lo faltante en amarillo y el motivo al final.
    r = cliente_http.get(f"/api/importar/trabajos/{trabajo_id}/errores", headers=h)
    assert r.status_code == 200 and "corregir_filial.xlsx" in r.headers["content-disposition"]
    ws = load_workbook(BytesIO(r.content))["Santiago"]
    titulos = [c.value for c in ws[1]]
    assert titulos[:len(TITULOS)] == TITULOS and titulos[-1] == "Motivo del error"
    filas = {ws.cell(i, 2).value: i for i in range(2, ws.max_row + 1)}
    assert set(filas) == {"2003-3", "2004-4", "2005-5"}
    amarillas = {(fila, c.column - 1) for fila, i in filas.items() for c in ws[i]
                 if c.fill.fgColor.rgb in ("00FFEB3B", "FFFFEB3B")}
    assert amarillas == {("2003-3", 7), ("2004-4", 4), ("2005-5", 6)}

    # Se completa y se sube tal cual: entran las 3 (el motivo se ignora).
    ws.cell(filas["2003-3"], 8).value = "Deudor 573"
    ws.cell(filas["2004-4"], 5).value = 120000
    ws.cell(filas["2005-5"], 7).value = rut_valido(576)
    salida = BytesIO()
    ws.parent.save(salida)
    res = cargar(cliente_http, h, "/api/importar/cobranzas", salida.getvalue(), {"cliente_id": cliente})
    assert res["cobranzas_creadas"] == 3 and res["total_errores"] == 0 and res["campos_creados"] == []


def test_fila_que_falla_no_deja_rastros_en_la_carga(cliente_http, org_a):
    """Si la primera fila de una filial nueva falla, la filial se deshace y las filas siguientes la crean bien."""
    h = login(cliente_http, org_a["email"])
    cliente = _cliente(cliente_http, h, 580)
    contenido = _libro({"Vitacura": [_fila("VITACURA", "3001-1", 581, monto=None),   # sin saldo: no entra
                                     _fila("VITACURA", "3002-2", 582)]})
    res = cargar(cliente_http, h, "/api/importar/cobranzas", contenido, {"cliente_id": cliente})
    assert res["cobranzas_creadas"] == 1 and res["total_errores"] == 1
    assert res["deudores_nuevos"] == 1 and res["filiales_creadas"] == ["Vitacura"]
    cobs = cliente_http.get("/api/cobranzas/", params={"cliente_id": cliente}, headers=h).json()
    assert [c["filial_nombre"] for c in cobs] == ["Vitacura"]


def test_pasar_a_produccion_no_espera_para_siempre(cliente_http, monkeypatch):
    """Si otra conexión tiene tomada una tabla, el borrado termina en error al rato (antes quedaba "Borrando…" sin fin)."""
    from app import produccion
    from app.database import engine

    monkeypatch.setattr(produccion, "ESPERA_BLOQUEO", "1s")
    org = crear_organizacion()
    h = login(cliente_http, org["email"])
    crear_cartera(cliente_http, h, n=590)
    otra = engine.connect()
    transaccion = otra.begin()
    try:
        otra.execute(text("LOCK TABLE cobranzas IN ROW EXCLUSIVE MODE"))
        r = cliente_http.post("/api/organizacion/produccion", headers=h,
                              json={"confirmacion": cliente_http.get("/api/organizacion", headers=h).json()["nombre"]})
        trabajo = cliente_http.get(f"/api/importar/trabajos/{r.json()['trabajo_id']}", headers=h).json()
        assert trabajo["estado"] == "error" and "No se borró nada" in trabajo["resultado"]["error"], trabajo
    finally:
        transaccion.rollback()
        otra.close()
    assert cliente_http.get("/api/organizacion/produccion", headers=h).json()["datos_de_prueba"]["cobranzas"] == 1
    # Liberada la tabla, sí se puede.
    r = cliente_http.post("/api/organizacion/produccion", headers=h,
                          json={"confirmacion": cliente_http.get("/api/organizacion", headers=h).json()["nombre"]})
    trabajo = cliente_http.get(f"/api/importar/trabajos/{r.json()['trabajo_id']}", headers=h).json()
    assert trabajo["estado"] == "terminado", trabajo
    assert cliente_http.get("/api/organizacion/produccion", headers=h).json()["datos_de_prueba"]["cobranzas"] == 0


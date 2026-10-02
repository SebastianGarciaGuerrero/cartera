"""
Aislamiento entre organizaciones: lo más importante de un SaaS.
Un estudio NUNCA debe poder ver ni tocar datos de otro, ni por la API ni
aunque el código tuviera un error (la base lo impide igual).
"""

import psycopg2
import pytest

from tests.conftest import URL_TEST, crear_cartera, login


def test_todas_las_tablas_con_organizacion_tienen_rls(cliente_http):
    """
    Guardia para migraciones futuras: tabla nueva sin política = test rojo.
    Se acepta también una tabla interna (RLS activo y sin ningún permiso
    para el rol de la app, como `sesiones`).
    """
    with psycopg2.connect(URL_TEST) as c, c.cursor() as cur:
        cur.execute("""
            SELECT t.table_name
            FROM information_schema.columns t
            JOIN pg_class k ON k.relname = t.table_name AND k.relkind = 'r'
            WHERE t.table_schema = 'public' AND t.column_name = 'organizacion_id'
              AND (NOT k.relrowsecurity OR (
                    has_table_privilege('cartera_app', k.oid, 'SELECT')
                    AND NOT EXISTS (
                        SELECT 1 FROM pg_policies p
                        WHERE p.tablename = t.table_name AND 'cartera_app' = ANY (p.roles))))
        """)
        sin_proteccion = [r[0] for r in cur.fetchall()]
    assert sin_proteccion == []


def test_api_no_muestra_datos_de_otra_organizacion(cliente_http, org_a, org_b):
    ha = login(cliente_http, org_a["email"])
    hb = login(cliente_http, org_b["email"])
    cartera_a = crear_cartera(cliente_http, ha, n=1)
    cartera_b = crear_cartera(cliente_http, hb, n=1)  # mismo RUT de deudor: permitido

    # Listados: cada uno ve solo lo suyo.
    ids_a = {c["id"] for c in cliente_http.get("/api/cobranzas/", headers=ha).json()}
    assert ids_a == {cartera_a["cobranza_id"]}
    assert len(cliente_http.get("/api/deudores/", headers=hb).json()) == 1

    # Acceso directo por id ajeno: 404 (igual que si no existiera).
    assert cliente_http.get(f"/api/cobranzas/{cartera_b['cobranza_id']}", headers=ha).status_code == 404
    assert cliente_http.get(f"/api/deudores/{cartera_b['deudor_id']}", headers=ha).status_code == 404
    assert cliente_http.put(f"/api/cobranzas/{cartera_b['cobranza_id']}", headers=ha,
                            json={"estado": "castigo"}).status_code == 404

    # Búsqueda: no aparece el deudor homónimo de la otra organización.
    resultados = cliente_http.get("/api/cobranzas/buscar", params={"q": "Deudor"}, headers=ha).json()
    assert {r["id"] for r in resultados} == {cartera_a["cobranza_id"]}


def test_no_se_puede_enlazar_a_registros_ajenos(cliente_http, org_a, org_b):
    ha = login(cliente_http, org_a["email"])
    hb = login(cliente_http, org_b["email"])
    cartera_a = crear_cartera(cliente_http, ha, n=2)
    cartera_b = crear_cartera(cliente_http, hb, n=3)

    # Cobranza en A apuntando al deudor de B.
    r = cliente_http.post("/api/cobranzas/", headers=ha, json={
        "cliente_id": cartera_a["cliente_id"], "deudor_id": cartera_b["deudor_id"],
        "monto_original": 1000,
    })
    assert r.status_code == 404

    # Gestión y pago sobre la cobranza de B.
    r = cliente_http.post("/api/gestiones/", headers=ha,
                          json={"cobranza_id": cartera_b["cobranza_id"], "descripcion": "x"})
    assert r.status_code == 404
    r = cliente_http.post("/api/pagos/", headers=ha,
                          json={"cobranza_id": cartera_b["cobranza_id"], "monto": 10, "capital": 10})
    assert r.status_code == 404


def test_numero_de_cobranza_correlativo_por_organizacion(cliente_http, org_a, org_b):
    ha = login(cliente_http, org_a["email"])
    hb = login(cliente_http, org_b["email"])
    a1 = crear_cartera(cliente_http, ha, n=4)
    b1 = crear_cartera(cliente_http, hb, n=4)
    assert a1["numero"] == 1000 and b1["numero"] == 1000


def _como_app(cur, org_id):
    cur.execute("SET ROLE cartera_app")
    cur.execute("SELECT set_config('app.organizacion_id', %s, false)", (str(org_id),))


def test_rls_protege_aunque_el_codigo_no_filtre(cliente_http, org_a, org_b):
    """SQL crudo sin WHERE, como lo haría un bug: la base filtra igual."""
    ha = login(cliente_http, org_a["email"])
    hb = login(cliente_http, org_b["email"])
    crear_cartera(cliente_http, ha, n=5)
    cartera_b = crear_cartera(cliente_http, hb, n=6)

    with psycopg2.connect(URL_TEST) as c, c.cursor() as cur:
        _como_app(cur, org_a["org_id"])
        cur.execute("SELECT DISTINCT organizacion_id FROM cobranzas")
        assert {r[0] for r in cur.fetchall()} == {str(org_a["org_id"])}
        cur.execute("SELECT count(*) FROM vista_deudor_cobranzas WHERE organizacion_id = %s",
                    (str(org_b["org_id"]),))
        assert cur.fetchone()[0] == 0
        c.rollback()

    # Escribir en otra organización: rechazado por la política.
    with psycopg2.connect(URL_TEST) as c, c.cursor() as cur:
        _como_app(cur, org_a["org_id"])
        with pytest.raises(psycopg2.Error):
            cur.execute("UPDATE cobranzas SET observaciones = 'hack' WHERE id = %s RETURNING id",
                        (cartera_b["cobranza_id"],))
            if cur.fetchone() is None:
                raise psycopg2.Error("sin filas: RLS la ocultó")


def test_rol_app_no_ve_sesiones_ni_puede_borrar(cliente_http, org_a):
    ha = login(cliente_http, org_a["email"])
    cartera = crear_cartera(cliente_http, ha, n=7)
    with psycopg2.connect(URL_TEST) as c, c.cursor() as cur:
        _como_app(cur, org_a["org_id"])
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cur.execute("SELECT * FROM sesiones")
    with psycopg2.connect(URL_TEST) as c, c.cursor() as cur:
        _como_app(cur, org_a["org_id"])
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cur.execute("DELETE FROM cobranzas WHERE id = %s", (cartera["cobranza_id"],))


def test_gestiones_y_pagos_son_inmutables_en_la_base(cliente_http, org_a):
    ha = login(cliente_http, org_a["email"])
    cartera = crear_cartera(cliente_http, ha, n=8)
    r = cliente_http.post("/api/gestiones/", headers=ha,
                          json={"cobranza_id": cartera["cobranza_id"], "descripcion": "Llamada"})
    assert r.status_code == 201
    gestion_id = r.json()["id"]
    # Incluso como dueño de las tablas (sin RLS), el trigger lo impide.
    with psycopg2.connect(URL_TEST) as c, c.cursor() as cur:
        with pytest.raises(psycopg2.Error):
            cur.execute("UPDATE gestiones SET descripcion = 'otra' WHERE id = %s", (gestion_id,))
    with psycopg2.connect(URL_TEST) as c, c.cursor() as cur:
        with pytest.raises(psycopg2.Error):
            cur.execute("DELETE FROM gestiones WHERE id = %s", (gestion_id,))


def test_fk_compuesta_impide_mezclar_organizaciones(cliente_http, org_a, org_b):
    """Aunque se salte la API y el ORM, la base rechaza el cruce."""
    ha = login(cliente_http, org_a["email"])
    hb = login(cliente_http, org_b["email"])
    cartera_a = crear_cartera(cliente_http, ha, n=9)
    cartera_b = crear_cartera(cliente_http, hb, n=10)
    with psycopg2.connect(URL_TEST) as c, c.cursor() as cur:
        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            cur.execute(
                "INSERT INTO cobranzas (organizacion_id, cliente_id, deudor_id, monto_original, monto_actual) "
                "VALUES (%s, %s, %s, 1, 1)",
                (str(org_a["org_id"]), cartera_a["cliente_id"], cartera_b["deudor_id"]),
            )

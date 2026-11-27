"""
Pasar a producción: borrar los datos de prueba de UNA organización y fijar
el N° de su primera cobranza real. Se hace una sola vez (queda marcado en
organizaciones.configuracion["en_produccion"]) y solo el administrador.

Se borra la cartera completa: cobranzas, deudores, terceros, gestiones,
pagos, acuerdos, causas, trámites, gastos, rendiciones, recordatorios,
enlaces del deudor, cargas; y los clientes y filiales de prueba (salvo un
cliente con usuarios del portal, que se conserva).
Se conserva: usuarios, datos de la empresa y su logo, configuración
(permisos, etiquetas, plantillas), tipos de gestión, trámites y tribunales
propios, campos adicionales generales y las bitácoras (auditoría y accesos).

Es el único lugar donde se borra físicamente: corre como dueño de las
tablas (modo sistema), con las protecciones de inmutabilidad apagadas solo
dentro de esta transacción, y filtrando siempre por la organización.
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.indicadores import hoy_chile

# Cuánto esperar si otra conexión tiene tomada una tabla (una carga en curso,
# una transacción colgada): sin esto el borrado esperaba para siempre y la
# pantalla quedaba "Borrando…" sin respuesta.
ESPERA_BLOQUEO = "20s"

CONSERVAR = {"organizaciones", "usuarios", "empresa", "sesiones", "tokens_un_uso", "eventos_acceso",
             "audit_log", "tipos_gestion", "tipos_tramite", "tribunales", "campos_personalizados", "roles"}
ESPECIALES = {"clientes", "filiales"}  # se borran aparte (un cliente con usuarios del portal se conserva)


def _tablas_de_cartera(db: Session) -> list[str]:
    """Tablas con datos de la organización a borrar, hijas antes que madres."""
    tablas = {r[0] for r in db.execute(text("""
        SELECT c.table_name FROM information_schema.columns c
        JOIN information_schema.tables t ON t.table_name = c.table_name AND t.table_schema = c.table_schema
        WHERE c.table_schema = 'public' AND c.column_name = 'organizacion_id' AND t.table_type = 'BASE TABLE'
    """))} - CONSERVAR - ESPECIALES
    madres: dict[str, set] = {t: set() for t in tablas}
    for hija, madre in db.execute(text("""
        SELECT conrelid::regclass::text, confrelid::regclass::text FROM pg_constraint
        WHERE contype = 'f' AND connamespace = 'public'::regnamespace
    """)):
        if hija in tablas and madre in tablas and hija != madre:
            madres[hija].add(madre)
    # Orden: una tabla se borra cuando ninguna otra pendiente la referencia.
    orden, pendientes = [], set(tablas)
    while pendientes:
        libres = sorted(t for t in pendientes if not any(t in madres[o] for o in pendientes if o != t))
        if not libres:
            raise RuntimeError(f"Referencias circulares entre: {sorted(pendientes)}")
        orden += libres
        pendientes -= set(libres)
    return orden


def conteos(db: Session, organizacion_id: UUID) -> dict:
    """Lo que se borraría (para mostrarlo antes de confirmar)."""
    resultado = {}
    for tabla in ("cobranzas", "deudores", "gestiones", "pagos", "acuerdos_pago", "causas", "clientes"):
        resultado[tabla] = db.execute(text(f"SELECT count(*) FROM {tabla} WHERE organizacion_id = :org"),
                                      {"org": organizacion_id}).scalar()
    return resultado


def pasar_a_produccion(db: Session, organizacion_id: UUID, numero_inicial: int, usuario_id: UUID) -> dict:
    """db: sesión en modo sistema. No hace commit (lo hace quien llama)."""
    org = {"org": organizacion_id}
    db.execute(text(f"SET LOCAL lock_timeout = '{ESPERA_BLOQUEO}'"))
    tablas = _tablas_de_cartera(db)
    con_triggers = {r[0] for r in db.execute(text(
        "SELECT DISTINCT tgrelid::regclass::text FROM pg_trigger WHERE NOT tgisinternal"))}
    apagar = [t for t in tablas if t in con_triggers]
    for tabla in apagar:
        db.execute(text(f"ALTER TABLE public.{tabla} DISABLE TRIGGER USER"))
    borrado = {}
    for tabla in tablas:
        borrado[tabla] = db.execute(text(f"DELETE FROM public.{tabla} WHERE organizacion_id = :org"), org).rowcount
    for tabla in apagar:
        db.execute(text(f"ALTER TABLE public.{tabla} ENABLE TRIGGER USER"))

    # Clientes de prueba (y sus filiales y campos propios), salvo los que tienen usuarios del portal.
    sin_portal = """organizacion_id = :org AND id NOT IN
                    (SELECT cliente_id FROM usuarios WHERE organizacion_id = :org AND cliente_id IS NOT NULL)"""
    borrado["campos_personalizados"] = db.execute(text(f"""
        DELETE FROM campos_personalizados WHERE organizacion_id = :org
          AND cliente_id IN (SELECT id FROM clientes WHERE {sin_portal})"""), org).rowcount
    borrado["filiales"] = db.execute(text(f"""
        DELETE FROM filiales WHERE organizacion_id = :org
          AND cliente_id IN (SELECT id FROM clientes WHERE {sin_portal})"""), org).rowcount
    borrado["clientes"] = db.execute(text(f"DELETE FROM clientes WHERE {sin_portal}"), org).rowcount

    db.execute(text("""
        UPDATE organizaciones
           SET numero_cobranza_siguiente = :n,
               configuracion = configuracion || jsonb_build_object(
                   'en_produccion', CAST(:desde AS text), 'numero_inicial', :n, 'pasado_por', CAST(:u AS text))
         WHERE id = :org
    """), {**org, "n": numero_inicial, "desde": hoy_chile().isoformat(), "u": str(usuario_id)})
    return {k: v for k, v in borrado.items() if v}


def ya_en_produccion(configuracion: dict | None) -> str | None:
    return (configuracion or {}).get("en_produccion")


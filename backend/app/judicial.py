"""
Reglas del módulo judicial (las usan routers/judicial.py y routers/gastos.py).

  - crear_causa: presenta la demanda. Las cobranzas incluidas (mismo deudor
    y mismo cliente) pasan a etapa judicial y queda una gestión en cada una.
  - registrar_tramite: anota lo que pasó en la causa. Si el trámite tiene
    plazo, queda la fecha para revisar y el trámite que suele venir después;
    si tiene etapa, la causa pasa a esa etapa. Puede llevar su gasto.
  - terminar_causa: cierra la causa y, si no queda otra causa vigente, cierra
    sus cobranzas con el estado que corresponde al resultado.
  - plazos: el plazo pendiente de una causa es el del ÚLTIMO trámite con
    tipo (las observaciones no lo cumplen). Además se vigila el abandono del
    procedimiento (6 meses sin trámites).

Todo corre en la transacción de quien llama (sin commit).
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable, List, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import ciclo
from app.models.cobranza import Cobranza
from app.models.judicial import Causa, CausaCobranza, Gasto, TipoTramite, Tramite
from app.operaciones import clp, gestion_automatica

PROCEDIMIENTOS = {
    "ejecutivo": "Juicio ejecutivo",
    "notificacion_cheque": "Notificación de protesto de cheque",
    "notificacion_factura": "Notificación de factura",
    "notificacion_letra": "Notificación de protesto de letra o pagaré",
    "confesion_deuda": "Citación a confesar deuda o reconocer firma",
    "ordinario": "Juicio ordinario",
    "sumario": "Juicio sumario",
    "exhorto": "Exhorto",
    "liquidacion": "Verificación de crédito en liquidación",
    "querella": "Querella criminal",
    "otro": "Otro",
}

# Primer trámite que queda registrado al presentar la demanda.
TRAMITE_INICIAL = {
    "confesion_deuda": "citacion_confesar",
    "querella": "querella",
}
TRAMITE_INICIAL_DEFECTO = "demanda_presentada"

ETAPAS_PROCESALES = {
    "demanda": "Demanda",
    "notificacion": "Notificación",
    "embargo": "Embargo",
    "defensa": "Excepciones y sentencia",
    "remate": "Remate y pago",
}

# Resultado de una causa → estado y motivo de cierre de sus cobranzas.
RESULTADOS = {
    "pagada": ("Pagada", "pagada", "pagada"),
    "avenimiento_cumplido": ("Avenimiento cumplido", "pagada", "avenimiento_cumplido"),
    "castigo": ("Castigo", "castigo", None),  # el motivo lo elige la persona
    "desistida": ("Desistimiento", "archivada", "desistida"),
    "abandono": ("Abandono del procedimiento", "archivada", "abandono"),
    "prescrita": ("Acción prescrita", "castigo", "prescrita"),
    "archivada": ("Archivada", "archivada", "otro"),
    "devuelta": ("Devuelta al cliente", "archivada", "devuelta_cliente"),
}

TIPOS_BIEN = {
    "vehiculo": "Vehículo",
    "inmueble": "Inmueble",
    "cuenta_bancaria": "Cuenta bancaria",
    "remuneraciones": "Remuneraciones",
    "muebles": "Bienes muebles",
    "otro": "Otro",
}
ESTADOS_EMBARGO = {
    "solicitado": "Solicitado",
    "trabado": "Trabado",
    "frustrado": "Frustrado",
    "retirado": "Retirado",
    "rematado": "Rematado",
    "alzado": "Alzado",
}
TIPOS_GASTO = {
    "receptor": "Receptor",
    "notificacion": "Notificación",
    "embargo": "Embargo",
    "fuerza_publica": "Fuerza pública",
    "conservador": "Conservador",
    "copias": "Copias y certificados",
    "publicacion": "Publicación",
    "martillero": "Martillero",
    "correo": "Correo y cartas",
    "otro": "Otro",
}
ESTADOS_GASTO = {
    "por_rendir": "Por rendir",
    "rendido": "Rendido (por reembolsar)",
    "reembolsado": "Reembolsado",
    "no_reembolsable": "No reembolsable",
    "anulado": "Anulado",
}

DIAS_ABANDONO = 180          # el abandono se produce a los 6 meses sin gestión útil
DIAS_AVISO_ABANDONO = 150    # se avisa un mes antes


def _400(detalle: str) -> HTTPException:
    return HTTPException(status_code=400, detail=detalle)


def tipo_por_codigo(db: Session, codigo: str) -> Optional[TipoTramite]:
    return (db.query(TipoTramite)
            .filter(TipoTramite.codigo == codigo, TipoTramite.organizacion_id.is_(None))
            .first())


def caratula_sugerida(cliente_nombre: str, deudor_nombre: str) -> str:
    return f"{cliente_nombre} con {deudor_nombre}"[:250]


def validar_cobranzas_para_causa(db: Session, cobranza_ids: Iterable[UUID],
                                 cliente_id: Optional[UUID] = None,
                                 deudor_id: Optional[UUID] = None) -> List[Cobranza]:
    """Todas existen, siguen abiertas y son del mismo deudor y cliente."""
    cobranzas = []
    for cid in dict.fromkeys(cobranza_ids):
        cob = db.get(Cobranza, cid)
        if cob is None:
            raise HTTPException(status_code=404, detail="Una de las cobranzas indicadas no existe")
        if cob.estado in ciclo.ESTADOS_TERMINALES:
            raise _400(f"La cobranza N° {cob.numero} está cerrada ({cob.estado}).")
        cliente_id = cliente_id or cob.cliente_id
        deudor_id = deudor_id or cob.deudor_id
        if cob.cliente_id != cliente_id or cob.deudor_id != deudor_id:
            raise _400("Una demanda solo puede incluir cobranzas del mismo deudor y del mismo cliente.")
        cobranzas.append(cob)
    if not cobranzas:
        raise _400("Indique al menos una cobranza para la demanda.")
    return cobranzas


def pasar_a_judicial(db: Session, cobranza: Cobranza, causa: Causa, usuario_id: UUID,
                     tribunal_nombre: Optional[str]) -> None:
    donde = " ".join(p for p in (f"rol {causa.rol}" if causa.rol else "",
                                 f"en {tribunal_nombre}" if tribunal_nombre else "") if p)
    if cobranza.etapa != "judicial":
        ciclo.fijar_contexto(db, usuario_id, f"Demanda presentada {donde}".strip())
        cobranza.etapa = "judicial"
    cobranza.estado = "judicial"
    cobranza.tipo = "judicial"
    if cobranza.fecha_traspaso is None:
        cobranza.fecha_traspaso = causa.fecha_ingreso
    db.add(CausaCobranza(causa=causa, cobranza_id=cobranza.id))
    gestion_automatica(
        db, cobranza.id, usuario_id, "demanda",
        f"DEMANDA PRESENTADA: {PROCEDIMIENTOS.get(causa.procedimiento, causa.procedimiento)}"
        + (f", {donde}" if donde else "") + ".",
    )


def crear_causa(db: Session, datos: dict, cobranza_ids: List[UUID], usuario_id: UUID,
                tribunal_nombre: Optional[str]) -> Causa:
    cobranzas = validar_cobranzas_para_causa(db, cobranza_ids)
    primera = cobranzas[0]
    if datos.get("cuantia") is None:
        datos["cuantia"] = sum((Decimal(c.monto_actual) for c in cobranzas), Decimal(0))
    if not datos.get("caratula"):
        cliente = primera.cliente
        datos["caratula"] = caratula_sugerida(
            (cliente.nombre_fantasia or cliente.razon_social) if cliente else "Demandante",
            primera.deudor.nombre if primera.deudor else "Demandado",
        )
    causa = Causa(**datos, cliente_id=primera.cliente_id, deudor_id=primera.deudor_id,
                  creado_por=usuario_id)
    db.add(causa)
    db.flush()
    for cob in cobranzas:
        pasar_a_judicial(db, cob, causa, usuario_id, tribunal_nombre)
    ciclo.fijar_contexto(db, usuario_id, "")

    inicial = tipo_por_codigo(db, TRAMITE_INICIAL.get(causa.procedimiento, TRAMITE_INICIAL_DEFECTO))
    if inicial is not None:
        registrar_tramite(db, causa, inicial, causa.fecha_ingreso, None, usuario_id)
    return causa


def registrar_tramite(db: Session, causa: Causa, tipo: Optional[TipoTramite], fecha: date,
                      descripcion: Optional[str], usuario_id: UUID,
                      plazo_fecha: Optional[date] = None,
                      siguiente_id: Optional[int] = None,
                      gasto: Optional[dict] = None, sin_plazo: bool = False) -> Tramite:
    """
    Anota un trámite (o una observación si no hay tipo). El plazo se calcula
    con el del tipo, salvo que venga uno a mano.
    """
    if causa.estado != "vigente":
        raise _400("La causa está terminada: no se pueden agregar trámites.")
    if tipo is None and not (descripcion and descripcion.strip()):
        raise _400("Escriba la observación o elija un trámite.")
    if tipo is not None:
        if plazo_fecha is None and tipo.plazo_dias is not None and not sin_plazo:
            plazo_fecha = fecha + timedelta(days=tipo.plazo_dias)
        if siguiente_id is None:
            siguiente_id = tipo.siguiente_id
    tramite = Tramite(causa_id=causa.id, tipo_id=tipo.id if tipo else None, fecha=fecha,
                      descripcion=(descripcion or "").strip() or None, plazo_fecha=plazo_fecha,
                      siguiente_id=siguiente_id if tipo else None, usuario_id=usuario_id)
    db.add(tramite)
    db.flush()

    if tipo is not None and tipo.etapa and tipo.etapa != causa.etapa_procesal:
        causa.etapa_procesal = tipo.etapa

    if gasto:
        db.add(Gasto(
            cliente_id=causa.cliente_id, causa_id=causa.id, tramite_id=tramite.id,
            fecha=gasto.get("fecha") or fecha, tipo=gasto.get("tipo") or "receptor",
            concepto=(gasto.get("concepto") or (tipo.nombre if tipo else "Gasto judicial"))[:200],
            monto=gasto["monto"], proveedor=gasto.get("proveedor"),
            numero_boleta=gasto.get("numero_boleta"), usuario_id=usuario_id,
        ))
    return tramite


def terminar_causa(db: Session, causa: Causa, resultado: str, fecha: date, usuario_id: UUID,
                   motivo_cierre: Optional[str] = None, nota: Optional[str] = None) -> None:
    if causa.estado != "vigente":
        raise _400("La causa ya está terminada.")
    if resultado not in RESULTADOS:
        raise _400("Resultado desconocido.")
    nombre, estado_cobranza, motivo_defecto = RESULTADOS[resultado]
    motivo = motivo_cierre or motivo_defecto or "otro"
    if motivo not in ciclo.MOTIVOS_CIERRE:
        raise _400("Motivo de cierre desconocido.")

    causa.estado = "terminada"
    causa.resultado = resultado
    causa.fecha_termino = fecha
    db.add(Tramite(causa_id=causa.id, tipo_id=None, fecha=fecha, usuario_id=usuario_id,
                   descripcion=f"CAUSA TERMINADA: {nombre}." + (f" {nota.strip()}" if nota and nota.strip() else "")))
    db.flush()

    for vinculo in causa.vinculos:
        cob = vinculo.cobranza
        otra_vigente = db.execute(text("""
            SELECT 1 FROM causa_cobranzas cc JOIN causas ca ON ca.id = cc.causa_id
            WHERE cc.cobranza_id = :c AND ca.id <> :causa AND ca.estado = 'vigente' LIMIT 1
        """), {"c": cob.id, "causa": causa.id}).first()
        if otra_vigente or cob.estado in ciclo.ESTADOS_TERMINALES:
            continue
        cob.estado = estado_cobranza
        cob.motivo_cierre = motivo
        cob.fecha_cierre = fecha
        gestion_automatica(
            db, cob.id, usuario_id, "otro" if estado_cobranza != "pagada" else "pagado",
            f"CAUSA TERMINADA ({causa.rol or 'sin rol'}): {nombre}. "
            f"Cobranza cerrada: {ciclo.MOTIVOS_CIERRE[motivo]}."
            + (f" {nota.strip()}" if nota and nota.strip() else ""),
        )


# ------------------------------------------------------------------ consultas

# Último trámite con tipo de cada causa (las observaciones no cuentan), por
# índice sobre (causa_id, fecha): no recorre los trámites de toda la organización.
_ULTIMO_TRAMITE = """
    LATERAL (
        SELECT tr.fecha AS ultima_fecha, tr.plazo_fecha, tr.siguiente_id,
               tt.nombre AS ultimo_tramite, sig.nombre AS siguiente_nombre
        FROM tramites tr
        JOIN tipos_tramite tt ON tt.id = tr.tipo_id
        LEFT JOIN tipos_tramite sig ON sig.id = tr.siguiente_id
        WHERE tr.causa_id = ca.id AND tr.tipo_id IS NOT NULL
        ORDER BY tr.fecha DESC, tr.created_at DESC
        LIMIT 1
    ) u
"""


def listar_causas(db: Session, organizacion_id: UUID, hoy: date, *, estado: Optional[str] = "vigente",
                  etapa: Optional[str] = None, cliente_id: Optional[UUID] = None,
                  responsable_id: Optional[UUID] = None, q: Optional[str] = None,
                  plazo: Optional[str] = None, limite: int = 100, desde: int = 0) -> tuple[int, List[dict]]:
    """
    Causas con su último trámite y su plazo pendiente, para la bandeja.
    plazo: 'vencido' / 'semana' (vence en 7 días) / 'abandono' (riesgo).
    """
    filtros = ["ca.organizacion_id = :org"]
    params: dict = {"org": organizacion_id, "hoy": hoy, "lim": limite, "desde": desde,
                    "dias_abandono": DIAS_AVISO_ABANDONO}
    if estado:
        filtros.append("ca.estado = :estado")
        params["estado"] = estado
    if etapa:
        filtros.append("ca.etapa_procesal = :etapa")
        params["etapa"] = etapa
    if cliente_id:
        filtros.append("ca.cliente_id = :cliente")
        params["cliente"] = cliente_id
    if responsable_id:
        filtros.append("(ca.abogado_id = :resp OR ca.procurador_id = :resp)")
        params["resp"] = responsable_id
    if q:
        filtros.append("""(ca.rol ILIKE :q OR d.nombre ILIKE :q OR replace(d.rut, '.', '') ILIKE :q
                           OR ca.caratula ILIKE :q
                           OR EXISTS (SELECT 1 FROM causa_cobranzas cc2 JOIN cobranzas c2 ON c2.id = cc2.cobranza_id
                                      WHERE cc2.causa_id = ca.id AND c2.numero::text = :q_exacto))""")
        params["q"] = f"%{q.replace('.', '').strip()}%"
        params["q_exacto"] = q.strip()
    if plazo == "vencido":
        filtros.append("u.plazo_fecha < :hoy")
    elif plazo == "semana":
        filtros.append("u.plazo_fecha BETWEEN :hoy AND CAST(:hoy AS date) + 7")
    elif plazo == "abandono":
        filtros.append("ca.estado = 'vigente' AND COALESCE(u.ultima_fecha, ca.fecha_ingreso) <= CAST(:hoy AS date) - :dias_abandono")

    where = " AND ".join(filtros)
    base = f"""
        SELECT ca.id, ca.rol, ca.procedimiento, ca.etapa_procesal, ca.estado, ca.resultado,
               ca.fecha_ingreso, ca.fecha_termino, ca.cuantia, ca.caratula,
               t.nombre AS tribunal, d.nombre AS deudor, d.rut AS deudor_rut,
               COALESCE(cl.nombre_fantasia, cl.razon_social) AS cliente,
               ab.nombre AS abogado, pr.nombre AS procurador,
               u.ultima_fecha, u.ultimo_tramite, u.plazo_fecha, u.siguiente_nombre,
               (SELECT array_agg(c.numero ORDER BY c.numero) FROM causa_cobranzas cc
                JOIN cobranzas c ON c.id = cc.cobranza_id WHERE cc.causa_id = ca.id) AS numeros_cobranza,
               (CAST(:hoy AS date) - COALESCE(u.ultima_fecha, ca.fecha_ingreso)) AS dias_sin_movimiento
        FROM causas ca
        JOIN deudores d ON d.id = ca.deudor_id
        JOIN clientes cl ON cl.id = ca.cliente_id
        LEFT JOIN tribunales t ON t.id = ca.tribunal_id
        LEFT JOIN usuarios ab ON ab.id = ca.abogado_id
        LEFT JOIN usuarios pr ON pr.id = ca.procurador_id
        LEFT JOIN {_ULTIMO_TRAMITE} ON true
        WHERE {where}
    """
    total = db.execute(text(f"SELECT count(*) FROM ({base}) x"), params).scalar()
    filas = db.execute(text(base + """
        ORDER BY (u.plazo_fecha IS NULL), u.plazo_fecha, ca.fecha_ingreso DESC
        LIMIT :lim OFFSET :desde
    """), params).mappings().all()
    return total, [dict(f) for f in filas]


def resumen_judicial(db: Session, organizacion_id: UUID, hoy: date) -> dict:
    """Números de la bandeja: causas por etapa y plazos."""
    params = {"org": organizacion_id, "hoy": hoy, "dias_abandono": DIAS_AVISO_ABANDONO}
    por_etapa = {r["etapa_procesal"]: r["n"] for r in db.execute(text("""
        SELECT etapa_procesal, count(*) AS n FROM causas
        WHERE organizacion_id = :org AND estado = 'vigente' GROUP BY etapa_procesal
    """), params).mappings()}
    plazos = db.execute(text(f"""
        SELECT
            count(*) FILTER (WHERE u.plazo_fecha < :hoy) AS vencidos,
            count(*) FILTER (WHERE u.plazo_fecha = :hoy) AS hoy,
            count(*) FILTER (WHERE u.plazo_fecha > :hoy AND u.plazo_fecha <= CAST(:hoy AS date) + 7) AS semana,
            count(*) FILTER (WHERE COALESCE(u.ultima_fecha, ca.fecha_ingreso)
                                   <= CAST(:hoy AS date) - :dias_abandono) AS riesgo_abandono
        FROM causas ca LEFT JOIN {_ULTIMO_TRAMITE} ON true
        WHERE ca.organizacion_id = :org AND ca.estado = 'vigente'
    """), params).mappings().one()
    para_demanda = db.execute(text("""
        SELECT count(*) FROM cobranzas
        WHERE organizacion_id = :org AND etapa = 'para_demanda' AND estado IN ('activa', 'acuerdo_pago')
    """), params).scalar()
    return {
        "vigentes": sum(por_etapa.values()),
        "por_etapa": {e: por_etapa.get(e, 0) for e in ETAPAS_PROCESALES},
        "plazos_vencidos": plazos["vencidos"],
        "plazos_hoy": plazos["hoy"],
        "plazos_semana": plazos["semana"],
        "riesgo_abandono": plazos["riesgo_abandono"],
        "para_demanda": para_demanda,
    }


def plazos_agenda(db: Session, organizacion_id: UUID, desde: date, hasta: date,
                  usuario_id: Optional[UUID]) -> List[dict]:
    """Plazos pendientes de causas vigentes entre dos fechas (para la agenda)."""
    filtro = ""
    params = {"org": organizacion_id, "desde": desde, "hasta": hasta, "usuario": usuario_id}
    if usuario_id is not None:
        filtro = "AND (ca.abogado_id = :usuario OR ca.procurador_id = :usuario OR ca.creado_por = :usuario)"
    return [dict(r) for r in db.execute(text(f"""
        SELECT ca.id AS causa_id, ca.rol, u.plazo_fecha, u.ultimo_tramite, u.siguiente_nombre,
               COALESCE(ca.procurador_id, ca.abogado_id, ca.creado_por) AS responsable_id,
               d.nombre AS deudor, t.nombre AS tribunal,
               (SELECT c.id FROM causa_cobranzas cc JOIN cobranzas c ON c.id = cc.cobranza_id
                WHERE cc.causa_id = ca.id ORDER BY c.numero LIMIT 1) AS cobranza_id,
               (SELECT min(c.numero) FROM causa_cobranzas cc JOIN cobranzas c ON c.id = cc.cobranza_id
                WHERE cc.causa_id = ca.id) AS numero_cobranza
        FROM causas ca
        JOIN {_ULTIMO_TRAMITE} ON true
        JOIN deudores d ON d.id = ca.deudor_id
        LEFT JOIN tribunales t ON t.id = ca.tribunal_id
        WHERE ca.organizacion_id = :org AND ca.estado = 'vigente'
          AND u.plazo_fecha BETWEEN :desde AND :hasta
          {filtro}
    """), params).mappings().all()]


def descripcion_gasto(monto) -> str:
    return clp(monto)

"""
Agenda: qué hay que hacer cada día, armado desde los datos que ya existen.

Un ítem de agenda sale de:
  - contacto / promesa: la ÚLTIMA gestión de cada cobranza abierta tiene
    `fecha_proximo_contacto`. Si después se registró otra gestión sin fecha,
    el compromiso se da por atendido.
  - cuota: cuotas abiertas (pendiente / parcial / vencida) de acuerdos
    vigentes, por fecha de vencimiento.
  - recordatorio: lo que cada persona se anotó (tabla `recordatorios`).
  - baja: acuerdo vigente con cuotas atrasadas que lleva 3 meses sin pagos
    de cuota (o sin pagar desde su primera cuota): sale cada día hasta que
    se da de baja o se paga.

Cada ítem va en una SECCIÓN (llamadas, WhatsApp, correos, cuotas vencidas…)
para ordenar el día: un contacto toma la del tipo de su última gestión; un
recordatorio, la de su tipo.

"De quién" es un ítem: de quien registró la gestión / el acuerdo (así le
llegan los avisos de las cuotas que pactó) y también del ejecutivo asignado
a la cobranza, si es otra persona.

Las consultas llevan el filtro de organización explícito además de la RLS.
"""

from dataclasses import dataclass, asdict
from datetime import date, time
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.agenda import Recordatorio
from app.operaciones import MESES_SIN_PAGO_BAJA, sumar_meses

ESTADOS_ABIERTOS = ("activa", "acuerdo_pago", "judicial")


# Sección de la agenda según el canal (código del tipo de gestión o tipo de recordatorio).
SECCION_CANAL = {
    "llamada": "llamadas", "no_contesta": "llamadas", "negativa_pago": "llamadas",
    "whatsapp": "whatsapp", "sms": "whatsapp", "email": "correos", "correo": "correos",
    "carta": "correos", "visita": "visitas", "tarea": "tareas",
}


@dataclass
class ItemAgenda:
    tipo: str                       # contacto / promesa / cuota / recordatorio / plazo / baja
    fecha: date
    titulo: str
    detalle: Optional[str] = None
    hora: Optional[time] = None
    atrasado: bool = False
    cobranza_id: Optional[UUID] = None
    numero_cobranza: Optional[int] = None
    deudor: Optional[str] = None
    monto: Optional[Decimal] = None
    responsable_id: Optional[UUID] = None
    recordatorio_id: Optional[UUID] = None
    cuota_id: Optional[UUID] = None
    causa_id: Optional[UUID] = None
    acuerdo_id: Optional[UUID] = None
    seccion: str = "tareas"         # bajas / cuotas_vencidas / cuotas / promesas / llamadas / whatsapp / …

    def dict(self):
        return asdict(self)


def _clp(v) -> str:
    return "$" + f"{int(v):,}".replace(",", ".")


def items_agenda(db: Session, organizacion_id: UUID, desde: date, hasta: date,
                 usuario_id: Optional[UUID], hoy: date) -> List[ItemAgenda]:
    params = {"org": organizacion_id, "desde": desde, "hasta": hasta, "usuario": usuario_id}
    filtro_contacto = ""
    filtro_cuota = ""
    if usuario_id is not None:
        filtro_contacto = "AND (c.ejecutivo_id = :usuario OR u.usuario_id = :usuario)"
        filtro_cuota = "AND (c.ejecutivo_id = :usuario OR ap.usuario_id = :usuario)"

    items: List[ItemAgenda] = []

    # Parte de las gestiones con fecha en el rango (índice parcial sobre
    # fecha_proximo_contacto) y se queda con las que siguen siendo la última
    # gestión de su cobranza: no recorre ni el historial ni toda la cartera.
    contactos = db.execute(text(f"""
        SELECT c.id AS cobranza_id, u.fecha_proximo_contacto, u.usuario_id, u.descripcion,
               t.codigo AS tipo_codigo, c.numero, c.monto_actual, c.ejecutivo_id,
               d.nombre AS deudor
        FROM gestiones u
        JOIN cobranzas c ON c.id = u.cobranza_id
        JOIN deudores d ON d.id = c.deudor_id
        LEFT JOIN tipos_gestion t ON t.id = u.tipo_id
        WHERE u.organizacion_id = :org
          AND u.fecha_proximo_contacto BETWEEN :desde AND :hasta
          AND c.estado IN ('activa', 'acuerdo_pago', 'judicial')
          AND NOT EXISTS (
              SELECT 1 FROM gestiones g2
              WHERE g2.organizacion_id = :org AND g2.cobranza_id = u.cobranza_id
                AND (g2.fecha_gestion, g2.created_at) > (u.fecha_gestion, u.created_at))
          {filtro_contacto}
    """), params).mappings().all()
    for r in contactos:
        es_promesa = r["tipo_codigo"] == "promesa_pago"
        items.append(ItemAgenda(
            tipo="promesa" if es_promesa else "contacto",
            fecha=r["fecha_proximo_contacto"],
            titulo=(f"Promesa de pago: {r['deudor']}" if es_promesa
                    else f"Contactar a {r['deudor']}"),
            detalle=(r["descripcion"] or "")[:300],
            atrasado=r["fecha_proximo_contacto"] < hoy,
            cobranza_id=r["cobranza_id"], numero_cobranza=r["numero"], deudor=r["deudor"],
            monto=r["monto_actual"], responsable_id=r["ejecutivo_id"] or r["usuario_id"],
            seccion="promesas" if es_promesa else SECCION_CANAL.get(r["tipo_codigo"] or "", "llamadas"),
        ))

    cuotas = db.execute(text(f"""
        SELECT cu.id, cu.fecha_vencimiento, cu.numero_cuota, cu.monto, cu.monto_pagado,
               ap.numero_cuotas, ap.usuario_id, c.id AS cobranza_id, c.numero,
               c.ejecutivo_id, d.nombre AS deudor
        FROM cuotas cu
        JOIN acuerdos_pago ap ON ap.id = cu.acuerdo_id
        JOIN cobranzas c ON c.id = ap.cobranza_id
        JOIN deudores d ON d.id = c.deudor_id
        WHERE cu.organizacion_id = :org
          AND ap.estado = 'vigente'
          AND c.estado IN ('activa', 'acuerdo_pago', 'judicial')
          AND cu.estado IN ('pendiente', 'pagada_parcial', 'vencida')
          AND cu.fecha_vencimiento BETWEEN :desde AND :hasta
          {filtro_cuota}
    """), params).mappings().all()
    for r in cuotas:
        saldo = Decimal(r["monto"]) - Decimal(r["monto_pagado"])
        items.append(ItemAgenda(
            tipo="cuota",
            fecha=r["fecha_vencimiento"],
            titulo=(f"Pie del acuerdo: {r['deudor']}" if r["numero_cuota"] == 0
                    else f"Cuota {r['numero_cuota']}/{r['numero_cuotas']}: {r['deudor']}"),
            detalle=f"Por pagar {_clp(saldo)}",
            atrasado=r["fecha_vencimiento"] < hoy,
            cobranza_id=r["cobranza_id"], numero_cobranza=r["numero"], deudor=r["deudor"],
            monto=saldo, responsable_id=r["ejecutivo_id"] or r["usuario_id"], cuota_id=r["id"],
            seccion="cuotas_vencidas" if r["fecha_vencimiento"] < hoy else "cuotas",
        ))

    q = db.query(Recordatorio).filter(
        Recordatorio.estado == "pendiente",
        Recordatorio.fecha >= desde, Recordatorio.fecha <= hasta,
    )
    if usuario_id is not None:
        q = q.filter(Recordatorio.usuario_id == usuario_id)
    for r in q.all():
        items.append(ItemAgenda(
            tipo="recordatorio", fecha=r.fecha, hora=r.hora, titulo=r.titulo, detalle=r.nota,
            atrasado=r.fecha < hoy, cobranza_id=r.cobranza_id,
            numero_cobranza=r.cobranza.numero if r.cobranza else None,
            deudor=r.cobranza.deudor.nombre if r.cobranza and r.cobranza.deudor else None,
            responsable_id=r.usuario_id, recordatorio_id=r.id,
            seccion=SECCION_CANAL.get(r.tipo or "tarea", "tareas"),
        ))

    # Plazos de las causas judiciales vigentes (del procurador o abogado a cargo).
    from app.judicial import plazos_agenda  # import local: judicial importa operaciones

    for p in plazos_agenda(db, organizacion_id, desde, hasta, usuario_id):
        siguiente = f" Sigue: {p['siguiente_nombre']}." if p["siguiente_nombre"] else ""
        items.append(ItemAgenda(
            tipo="plazo",
            fecha=p["plazo_fecha"],
            titulo=f"Plazo judicial: {p['deudor']}" + (f" (rol {p['rol']})" if p["rol"] else ""),
            detalle=f"Último trámite: {p['ultimo_tramite']}.{siguiente}"
                    + (f" {p['tribunal']}." if p["tribunal"] else ""),
            atrasado=p["plazo_fecha"] < hoy,
            cobranza_id=p["cobranza_id"], numero_cobranza=p["numero_cobranza"], deudor=p["deudor"],
            responsable_id=p["responsable_id"], causa_id=p["causa_id"], seccion="plazos",
        ))

    # Acuerdos para dar de baja: es una tarea de HOY (sale solo en el día de hoy).
    if desde <= hoy <= hasta:
        limite = sumar_meses(hoy, -MESES_SIN_PAGO_BAJA)
        bajas = db.execute(text(f"""
            SELECT * FROM (
                SELECT ap.id AS acuerdo_id, c.id AS cobranza_id, c.numero, d.nombre AS deudor,
                       c.ejecutivo_id, ap.usuario_id,
                       count(cu.id) FILTER (WHERE cu.estado <> 'pagada' AND cu.fecha_vencimiento < :hoy) AS atrasadas,
                       COALESCE(sum(cu.monto - cu.monto_pagado)
                                FILTER (WHERE cu.estado <> 'pagada' AND cu.fecha_vencimiento < :hoy), 0) AS atrasado,
                       min(cu.fecha_vencimiento) FILTER (WHERE cu.estado <> 'pagada') AS primera_impaga,
                       (SELECT max(p.fecha_pago) FROM pagos p JOIN cuotas cx ON cx.id = p.cuota_id
                        WHERE cx.acuerdo_id = ap.id AND p.anulado_at IS NULL) AS ultimo_pago
                FROM acuerdos_pago ap
                JOIN cobranzas c ON c.id = ap.cobranza_id
                JOIN deudores d ON d.id = c.deudor_id
                JOIN cuotas cu ON cu.acuerdo_id = ap.id
                WHERE ap.organizacion_id = :org AND ap.estado = 'vigente'
                  AND c.estado IN ('activa', 'acuerdo_pago', 'judicial')
                  {filtro_cuota}
                GROUP BY ap.id, c.id, c.numero, d.nombre, c.ejecutivo_id, ap.usuario_id
            ) x
            WHERE atrasadas > 0 AND COALESCE(ultimo_pago, primera_impaga) <= :limite
        """), {**params, "hoy": hoy, "limite": limite}).mappings().all()
        for r in bajas:
            desde_cuando = (f"sin pagos de cuota desde el {r['ultimo_pago'].strftime('%d-%m-%Y')}"
                            if r["ultimo_pago"] else
                            f"nunca pagó (primera cuota impaga del {r['primera_impaga'].strftime('%d-%m-%Y')})")
            items.append(ItemAgenda(
                tipo="baja", fecha=hoy,
                titulo=f"Acuerdo para dar de baja: {r['deudor']}",
                detalle=f"{r['atrasadas']} cuota(s) atrasada(s) por {_clp(r['atrasado'])}; {desde_cuando}.",
                atrasado=False, cobranza_id=r["cobranza_id"], numero_cobranza=r["numero"], deudor=r["deudor"],
                monto=r["atrasado"], responsable_id=r["ejecutivo_id"] or r["usuario_id"],
                acuerdo_id=r["acuerdo_id"], seccion="bajas",
            ))

    orden_tipo = {"baja": 0, "recordatorio": 1, "plazo": 2, "promesa": 3, "cuota": 4, "contacto": 5}
    items.sort(key=lambda i: (i.fecha, i.hora or time.min, orden_tipo[i.tipo], i.titulo))
    return items

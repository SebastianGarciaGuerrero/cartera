"""
Agenda: qué hay que hacer cada día, armado desde los datos que ya existen.

Un ítem de agenda sale de:
  - contacto / promesa: la ÚLTIMA gestión de cada cobranza abierta tiene
    `fecha_proximo_contacto`. Si después se registró otra gestión sin fecha,
    el compromiso se da por atendido.
  - cuota: cuotas abiertas (pendiente / parcial / vencida) de acuerdos
    vigentes, por fecha de vencimiento.
  - recordatorio: lo que cada persona se anotó (tabla `recordatorios`).

"De quién" es un ítem: del ejecutivo asignado a la cobranza; si la
cobranza no tiene ejecutivo, de quien registró la gestión / el acuerdo.

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

ESTADOS_ABIERTOS = ("activa", "acuerdo_pago", "judicial")


@dataclass
class ItemAgenda:
    tipo: str                       # contacto / promesa / cuota / recordatorio
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
        filtro_contacto = ("AND (c.ejecutivo_id = :usuario "
                           "OR (c.ejecutivo_id IS NULL AND u.usuario_id = :usuario))")
        filtro_cuota = ("AND (c.ejecutivo_id = :usuario "
                        "OR (c.ejecutivo_id IS NULL AND ap.usuario_id = :usuario))")

    items: List[ItemAgenda] = []

    contactos = db.execute(text(f"""
        WITH ultima AS (
            SELECT DISTINCT ON (g.cobranza_id)
                   g.cobranza_id, g.fecha_proximo_contacto, g.usuario_id,
                   g.descripcion, g.tipo_id
            FROM gestiones g
            WHERE g.organizacion_id = :org
            ORDER BY g.cobranza_id, g.fecha_gestion DESC, g.created_at DESC
        )
        SELECT u.cobranza_id, u.fecha_proximo_contacto, u.usuario_id, u.descripcion,
               t.codigo AS tipo_codigo, c.numero, c.monto_actual, c.ejecutivo_id,
               d.nombre AS deudor
        FROM ultima u
        JOIN cobranzas c ON c.id = u.cobranza_id
        JOIN deudores d ON d.id = c.deudor_id
        LEFT JOIN tipos_gestion t ON t.id = u.tipo_id
        WHERE c.organizacion_id = :org
          AND u.fecha_proximo_contacto BETWEEN :desde AND :hasta
          AND c.estado IN ('activa', 'acuerdo_pago', 'judicial')
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
          AND cu.estado IN ('pendiente', 'pagada_parcial', 'vencida')
          AND cu.fecha_vencimiento BETWEEN :desde AND :hasta
          {filtro_cuota}
    """), params).mappings().all()
    for r in cuotas:
        saldo = Decimal(r["monto"]) - Decimal(r["monto_pagado"])
        items.append(ItemAgenda(
            tipo="cuota",
            fecha=r["fecha_vencimiento"],
            titulo=f"Cuota {r['numero_cuota']}/{r['numero_cuotas']}: {r['deudor']}",
            detalle=f"Por pagar {_clp(saldo)}",
            atrasado=r["fecha_vencimiento"] < hoy,
            cobranza_id=r["cobranza_id"], numero_cobranza=r["numero"], deudor=r["deudor"],
            monto=saldo, responsable_id=r["ejecutivo_id"] or r["usuario_id"], cuota_id=r["id"],
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
        ))

    orden_tipo = {"recordatorio": 0, "promesa": 1, "cuota": 2, "contacto": 3}
    items.sort(key=lambda i: (i.fecha, i.hora or time.min, orden_tipo[i.tipo], i.titulo))
    return items

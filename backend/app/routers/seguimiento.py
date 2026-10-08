"""
Mi seguimiento: el panel de cada persona, armado con lo que va registrando.

  GET /api/seguimiento?dias=30            → mi panel
  GET /api/seguimiento?usuario_id=...     → el de otra persona (admin y supervisor)

Incluye lo de hoy, el período (gestiones, promesas y si se cumplieron,
acuerdos, pagos, cumplimiento de cuotas), las gestiones por día y por tipo,
sus acuerdos atrasados, las cuotas de los próximos 7 días y sus últimas
gestiones. "Sus" acuerdos son los que registró y los de las cobranzas que
tiene asignadas, igual que en la agenda.

No cuenta como trabajo propio lo que hace el sistema solo (tipo
'automatica', p. ej. el deudor abrió su enlace) ni el ingreso de la cobranza.

Los días son de Chile: las gestiones se traen por rango de instantes y se
agrupan en Python con la zona horaria (incluye el cambio de horario), sin
depender de que la base tenga cargadas las zonas horarias.
"""

from collections import Counter
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.indicadores import ZONA_CHILE, hoy_chile
from app.models.usuario import Usuario
from app.security import usuario_autorizado

router = APIRouter(prefix="/api/seguimiento", tags=["Mi seguimiento"])

VEN_A_OTROS = {"admin", "supervisor"}
# Margen para dar por cumplida una promesa: pago hasta 3 días después de la fecha.
GRACIA_PROMESA = 3

NO_AUTOMATICAS = ('automatica', 'ingreso')
MIS_ACUERDOS = "(ap.usuario_id = :u OR c.ejecutivo_id = :u)"


class ResumenDia(BaseModel):
    gestiones: int
    contactos: int
    promesas: int
    acuerdos: int


class ResumenPeriodo(ResumenDia):
    promesas_cumplidas: int
    promesas_vencidas: int
    monto_acordado: Decimal
    pagos_registrados: int
    monto_pagos: Decimal
    cuotas_vencidas: int
    cuotas_pagadas: int


class Dia(BaseModel):
    fecha: date
    gestiones: int


class PorTipo(BaseModel):
    tipo: str
    cantidad: int


class AcuerdoAtrasado(BaseModel):
    cobranza_id: UUID
    numero: int
    deudor: str
    cuotas_atrasadas: int
    monto_atrasado: Decimal
    desde: date


class ProximaCuota(BaseModel):
    cobranza_id: UUID
    numero: int
    deudor: str
    cuota: int
    de: int
    fecha: date
    monto: Decimal


class UltimaGestion(BaseModel):
    cobranza_id: UUID
    numero: int
    deudor: str
    tipo: Optional[str] = None
    descripcion: str
    fecha: datetime


class Seguimiento(BaseModel):
    usuario_id: UUID
    usuario: str
    desde: date
    hasta: date
    hoy: ResumenDia
    periodo: ResumenPeriodo
    por_dia: List[Dia]
    por_tipo: List[PorTipo]
    acuerdos_vigentes: int
    acuerdos_al_dia: int
    por_cobrar: Decimal
    atrasados: List[AcuerdoAtrasado]
    proximas_cuotas: List[ProximaCuota]
    ultimas: List[UltimaGestion]


def _instante(dia: date) -> datetime:
    """Medianoche de Chile de ese día."""
    return datetime.combine(dia, time.min, tzinfo=ZONA_CHILE)


@router.get("", response_model=Seguimiento)
def ver_seguimiento(
    dias: int = Query(30, ge=7, le=90),
    usuario_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_autorizado),
):
    if usuario_id and usuario_id != usuario.id:
        if usuario.rol_nombre not in VEN_A_OTROS:
            raise HTTPException(status_code=403, detail="Solo puedes ver tu propio seguimiento.")
        persona = db.get(Usuario, usuario_id)
        if persona is None:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
    else:
        persona = usuario

    hoy = hoy_chile()
    desde = hoy - timedelta(days=dias - 1)
    p = {"org": usuario.organizacion_id, "u": persona.id, "hoy": hoy}

    # Las gestiones propias del período, con su día en hora de Chile.
    filas = db.execute(text("""
        SELECT g.cobranza_id, g.fecha_gestion, g.fecha_proximo_contacto,
               t.codigo, t.categoria, coalesce(t.nombre, 'Sin tipo') AS tipo
        FROM gestiones g LEFT JOIN tipos_gestion t ON t.id = g.tipo_id
        WHERE g.organizacion_id = :org AND g.usuario_id = :u
          AND g.fecha_gestion >= :ini AND g.fecha_gestion < :fin
    """), {**p, "ini": _instante(desde), "fin": _instante(hoy + timedelta(days=1))}).mappings().all()
    gestiones = [dict(r, dia=r["fecha_gestion"].astimezone(ZONA_CHILE).date())
                 for r in filas if r["codigo"] not in NO_AUTOMATICAS]

    def contar(lista) -> dict:
        return {"gestiones": len(lista),
                "contactos": sum(1 for g in lista if g["categoria"] == "contacto"),
                "promesas": sum(1 for g in lista if g["codigo"] == "promesa_pago")}

    de_hoy = contar([g for g in gestiones if g["dia"] == hoy])
    periodo = contar(gestiones)
    por_dia = Counter(g["dia"] for g in gestiones)
    por_tipo = Counter(g["tipo"] for g in gestiones)

    acuerdos = db.execute(text("""
        SELECT created_at, monto_total_acordado FROM acuerdos_pago
        WHERE organizacion_id = :org AND usuario_id = :u AND created_at >= :ini AND created_at < :fin
    """), {**p, "ini": _instante(desde), "fin": _instante(hoy + timedelta(days=1))}).mappings().all()
    de_hoy["acuerdos"] = sum(1 for a in acuerdos if a["created_at"].astimezone(ZONA_CHILE).date() == hoy)
    periodo["acuerdos"] = len(acuerdos)
    periodo["monto_acordado"] = sum((a["monto_total_acordado"] for a in acuerdos), Decimal(0))

    # Promesa cumplida: hubo un pago en esa cobranza entre el día de la
    # promesa y la fecha prometida (más unos días de gracia).
    promesas = [g for g in gestiones if g["codigo"] == "promesa_pago" and g["fecha_proximo_contacto"]]
    pagos_cobranzas = {}
    if promesas:
        for r in db.execute(text("""
            SELECT cobranza_id, fecha_pago FROM pagos
            WHERE organizacion_id = :org AND cobranza_id = ANY(:ids) AND fecha_pago >= :d
        """), {**p, "ids": list({g["cobranza_id"] for g in promesas}), "d": desde}).mappings():
            pagos_cobranzas.setdefault(r["cobranza_id"], []).append(r["fecha_pago"])
    cumplidas = vencidas = 0
    for g in promesas:
        limite = g["fecha_proximo_contacto"] + timedelta(days=GRACIA_PROMESA)
        if any(g["dia"] <= f <= limite for f in pagos_cobranzas.get(g["cobranza_id"], [])):
            cumplidas += 1
        elif g["fecha_proximo_contacto"] < hoy:
            vencidas += 1

    pagos = db.execute(text("""
        SELECT count(*) AS n, coalesce(sum(monto), 0) AS monto FROM pagos
        WHERE organizacion_id = :org AND usuario_id = :u AND fecha_pago BETWEEN :d AND :hoy
    """), {**p, "d": desde}).mappings().one()

    cuotas = db.execute(text(f"""
        SELECT count(*) AS vencidas, count(*) FILTER (WHERE cu.estado = 'pagada') AS pagadas
        FROM cuotas cu
        JOIN acuerdos_pago ap ON ap.id = cu.acuerdo_id
        JOIN cobranzas c ON c.id = ap.cobranza_id
        WHERE cu.organizacion_id = :org AND {MIS_ACUERDOS}
          AND ap.estado IN ('vigente', 'cumplido', 'incumplido')
          AND cu.fecha_vencimiento BETWEEN :d AND :hoy
    """), {**p, "d": desde}).mappings().one()

    vigentes = db.execute(text(f"""
        SELECT count(DISTINCT ap.id) AS vigentes,
               coalesce(sum(cu.monto - cu.monto_pagado) FILTER (WHERE cu.estado <> 'pagada'), 0) AS por_cobrar
        FROM acuerdos_pago ap
        JOIN cobranzas c ON c.id = ap.cobranza_id
        LEFT JOIN cuotas cu ON cu.acuerdo_id = ap.id
        WHERE ap.organizacion_id = :org AND ap.estado = 'vigente' AND {MIS_ACUERDOS}
    """), p).mappings().one()

    atrasados = db.execute(text(f"""
        SELECT c.id AS cobranza_id, c.numero, d.nombre AS deudor,
               count(*) AS cuotas_atrasadas, sum(cu.monto - cu.monto_pagado) AS monto_atrasado,
               min(cu.fecha_vencimiento) AS desde
        FROM cuotas cu
        JOIN acuerdos_pago ap ON ap.id = cu.acuerdo_id
        JOIN cobranzas c ON c.id = ap.cobranza_id
        JOIN deudores d ON d.id = c.deudor_id
        WHERE cu.organizacion_id = :org AND ap.estado = 'vigente' AND {MIS_ACUERDOS}
          AND cu.estado <> 'pagada' AND cu.fecha_vencimiento < :hoy
        GROUP BY c.id, c.numero, d.nombre
        ORDER BY min(cu.fecha_vencimiento)
    """), p).mappings().all()

    proximas = db.execute(text(f"""
        SELECT c.id AS cobranza_id, c.numero, d.nombre AS deudor, cu.numero_cuota AS cuota,
               ap.numero_cuotas AS de, cu.fecha_vencimiento AS fecha, cu.monto - cu.monto_pagado AS monto
        FROM cuotas cu
        JOIN acuerdos_pago ap ON ap.id = cu.acuerdo_id
        JOIN cobranzas c ON c.id = ap.cobranza_id
        JOIN deudores d ON d.id = c.deudor_id
        WHERE cu.organizacion_id = :org AND ap.estado = 'vigente' AND {MIS_ACUERDOS}
          AND cu.estado <> 'pagada' AND cu.fecha_vencimiento BETWEEN :hoy AND CAST(:hoy AS date) + 7
        ORDER BY cu.fecha_vencimiento, c.numero
        LIMIT 30
    """), p).mappings().all()

    ultimas = db.execute(text("""
        SELECT c.id AS cobranza_id, c.numero, d.nombre AS deudor, t.nombre AS tipo,
               left(g.descripcion, 180) AS descripcion, g.fecha_gestion AS fecha
        FROM gestiones g
        JOIN cobranzas c ON c.id = g.cobranza_id
        JOIN deudores d ON d.id = c.deudor_id
        LEFT JOIN tipos_gestion t ON t.id = g.tipo_id
        WHERE g.organizacion_id = :org AND g.usuario_id = :u
          AND (t.codigo IS NULL OR t.codigo NOT IN ('automatica', 'ingreso'))
        ORDER BY g.fecha_gestion DESC, g.created_at DESC
        LIMIT 10
    """), p).mappings().all()

    return Seguimiento(
        usuario_id=persona.id, usuario=persona.nombre, desde=desde, hasta=hoy,
        hoy=ResumenDia(**de_hoy),
        periodo=ResumenPeriodo(
            **periodo, promesas_cumplidas=cumplidas, promesas_vencidas=vencidas,
            pagos_registrados=pagos["n"], monto_pagos=pagos["monto"],
            cuotas_vencidas=cuotas["vencidas"], cuotas_pagadas=cuotas["pagadas"],
        ),
        por_dia=[Dia(fecha=desde + timedelta(days=i), gestiones=por_dia[desde + timedelta(days=i)])
                 for i in range(dias)],
        por_tipo=[PorTipo(tipo=k, cantidad=v) for k, v in sorted(por_tipo.items(), key=lambda x: (-x[1], x[0]))],
        acuerdos_vigentes=vigentes["vigentes"],
        acuerdos_al_dia=vigentes["vigentes"] - len(atrasados),
        por_cobrar=vigentes["por_cobrar"],
        atrasados=[AcuerdoAtrasado(**r) for r in atrasados],
        proximas_cuotas=[ProximaCuota(**r) for r in proximas],
        ultimas=[UltimaGestion(**r) for r in ultimas],
    )

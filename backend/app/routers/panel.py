"""
Panel de indicadores.

  GET /api/panel?desde=&hasta=&cliente_id=&ejecutivo_id=

Devuelve en una sola llamada:
  - recupero del período y del período anterior (mismo largo) para comparar
  - cartera abierta por estado (cantidad y saldo)
  - cuotas atrasadas y cumplimiento de las cuotas que vencieron en el período
  - gestiones del período y cobranzas abiertas sin gestión hace 30+ días
  - recupero mensual de los últimos 12 meses (capital y honorarios)
  - resumen por mandante

Admin y supervisor ven todo (y pueden filtrar por ejecutivo); el resto ve
solo las cobranzas que tiene asignadas.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.indicadores import hoy_chile
from app.models.usuario import Usuario
from app.security import get_current_user, usuario_autorizado

router = APIRouter(prefix="/api/panel", tags=["Panel"], dependencies=[Depends(usuario_autorizado)])

ABIERTAS = "('activa', 'acuerdo_pago', 'judicial')"


class Recupero(BaseModel):
    total: Decimal
    capital: Decimal
    honorarios: Decimal
    intereses: Decimal
    pagos: int


class EstadoCartera(BaseModel):
    estado: str
    cantidad: int
    saldo: Decimal
    original: Decimal


class Mes(BaseModel):
    mes: date
    capital: Decimal
    honorarios: Decimal
    otros: Decimal
    total: Decimal


class PorCliente(BaseModel):
    cliente_id: UUID
    cliente: str
    abiertas: int
    saldo: Decimal
    asignado: Decimal
    recuperado_periodo: Decimal
    recuperado_total: Decimal


class Panel(BaseModel):
    desde: date
    hasta: date
    recupero: Recupero
    recupero_anterior: Recupero
    cartera: List[EstadoCartera]
    cuotas_atrasadas: int
    monto_atrasado: Decimal
    cuotas_vencidas_periodo: int
    cuotas_pagadas_periodo: int
    gestiones_periodo: int
    sin_gestion_30_dias: int
    meses: List[Mes]
    por_cliente: List[PorCliente]


def _primer_dia_mes(f: date, meses_atras: int = 0) -> date:
    total = f.year * 12 + f.month - 1 - meses_atras
    return date(total // 12, total % 12 + 1, 1)


@router.get("", response_model=Panel)
def panel(
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    cliente_id: Optional[UUID] = None,
    ejecutivo_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    hoy = hoy_chile()
    desde = desde or hoy.replace(day=1)
    hasta = hasta or hoy
    if hasta < desde or (hasta - desde).days > 366:
        raise HTTPException(status_code=422, detail="El período debe ser de hasta un año.")
    if usuario.rol_nombre not in ("admin", "supervisor"):
        ejecutivo_id = usuario.id  # cada uno ve lo suyo

    largo = (hasta - desde).days + 1
    p = {
        "org": usuario.organizacion_id, "desde": desde, "hasta": hasta, "hoy": hoy,
        "desde_ant": desde - timedelta(days=largo), "hasta_ant": desde - timedelta(days=1),
        "cli": cliente_id, "eje": ejecutivo_id,
        "inicio_serie": _primer_dia_mes(hoy, 11), "hace_30": hoy - timedelta(days=30),
    }
    filtro = ""
    if cliente_id is not None:
        filtro += " AND c.cliente_id = :cli"
    if ejecutivo_id is not None:
        filtro += " AND c.ejecutivo_id = :eje"

    def recupero(d: str, h: str) -> Recupero:
        r = db.execute(text(f"""
            SELECT COALESCE(SUM(p.monto), 0) AS total, COALESCE(SUM(p.capital), 0) AS capital,
                   COALESCE(SUM(p.honorarios), 0) AS honorarios,
                   COALESCE(SUM(p.intereses), 0) AS intereses, COUNT(*) AS pagos
            FROM pagos p JOIN cobranzas c ON c.id = p.cobranza_id
            WHERE p.organizacion_id = :org AND p.fecha_pago BETWEEN :{d} AND :{h} {filtro}
        """), p).mappings().one()
        return Recupero(**r)

    cartera = db.execute(text(f"""
        SELECT c.estado, COUNT(*) AS cantidad, COALESCE(SUM(c.monto_actual), 0) AS saldo,
               COALESCE(SUM(c.monto_original), 0) AS original
        FROM cobranzas c WHERE c.organizacion_id = :org {filtro}
        GROUP BY c.estado ORDER BY COUNT(*) DESC
    """), p).mappings().all()

    atrasadas = db.execute(text(f"""
        SELECT COUNT(*) AS n, COALESCE(SUM(cu.monto - cu.monto_pagado), 0) AS monto
        FROM cuotas cu JOIN acuerdos_pago ap ON ap.id = cu.acuerdo_id
        JOIN cobranzas c ON c.id = ap.cobranza_id
        WHERE cu.organizacion_id = :org AND ap.estado = 'vigente'
          AND cu.estado IN ('pendiente', 'pagada_parcial', 'vencida')
          AND cu.fecha_vencimiento < :hoy {filtro}
    """), p).mappings().one()

    cumplimiento = db.execute(text(f"""
        SELECT COUNT(*) AS vencidas, COUNT(*) FILTER (WHERE cu.estado = 'pagada') AS pagadas
        FROM cuotas cu JOIN acuerdos_pago ap ON ap.id = cu.acuerdo_id
        JOIN cobranzas c ON c.id = ap.cobranza_id
        WHERE cu.organizacion_id = :org AND ap.estado <> 'renegociado'
          AND cu.fecha_vencimiento BETWEEN :desde AND LEAST(:hasta, :hoy) {filtro}
    """), p).mappings().one()

    gestiones = db.execute(text(f"""
        SELECT COUNT(*) FROM gestiones g JOIN cobranzas c ON c.id = g.cobranza_id
        WHERE g.organizacion_id = :org AND g.fecha_gestion::date BETWEEN :desde AND :hasta {filtro}
    """), p).scalar()

    sin_gestion = db.execute(text(f"""
        SELECT COUNT(*) FROM cobranzas c
        WHERE c.organizacion_id = :org AND c.estado IN {ABIERTAS} {filtro}
          AND NOT EXISTS (SELECT 1 FROM gestiones g
                          WHERE g.cobranza_id = c.id AND g.fecha_gestion::date >= :hace_30)
    """), p).scalar()

    filas_mes = db.execute(text(f"""
        SELECT date_trunc('month', p.fecha_pago)::date AS mes,
               COALESCE(SUM(p.capital), 0) AS capital, COALESCE(SUM(p.honorarios), 0) AS honorarios,
               COALESCE(SUM(p.monto - p.capital - p.honorarios), 0) AS otros,
               COALESCE(SUM(p.monto), 0) AS total
        FROM pagos p JOIN cobranzas c ON c.id = p.cobranza_id
        WHERE p.organizacion_id = :org AND p.fecha_pago >= :inicio_serie {filtro}
        GROUP BY 1
    """), p).mappings().all()
    por_mes = {r["mes"]: r for r in filas_mes}
    meses = []
    for i in range(11, -1, -1):
        m = _primer_dia_mes(hoy, i)
        r = por_mes.get(m)
        meses.append(Mes(mes=m, capital=r["capital"], honorarios=r["honorarios"], otros=r["otros"],
                         total=r["total"]) if r else Mes(mes=m, capital=0, honorarios=0, otros=0, total=0))

    por_cliente = db.execute(text(f"""
        SELECT cl.id AS cliente_id, COALESCE(cl.nombre_fantasia, cl.razon_social) AS cliente,
               COUNT(*) FILTER (WHERE c.estado IN {ABIERTAS}) AS abiertas,
               COALESCE(SUM(c.monto_actual) FILTER (WHERE c.estado IN {ABIERTAS}), 0) AS saldo,
               COALESCE(SUM(c.monto_original), 0) AS asignado,
               COALESCE((SELECT SUM(p.capital) FROM pagos p JOIN cobranzas c2 ON c2.id = p.cobranza_id
                         WHERE c2.cliente_id = cl.id AND p.organizacion_id = :org
                           AND p.fecha_pago BETWEEN :desde AND :hasta
                           {filtro.replace('c.', 'c2.')}), 0) AS recuperado_periodo,
               COALESCE((SELECT SUM(p.capital) FROM pagos p JOIN cobranzas c2 ON c2.id = p.cobranza_id
                         WHERE c2.cliente_id = cl.id AND p.organizacion_id = :org
                           {filtro.replace('c.', 'c2.')}), 0) AS recuperado_total
        FROM clientes cl JOIN cobranzas c ON c.cliente_id = cl.id
        WHERE cl.organizacion_id = :org {filtro}
        GROUP BY cl.id, cl.nombre_fantasia, cl.razon_social
        ORDER BY saldo DESC
        LIMIT 50
    """), p).mappings().all()

    return Panel(
        desde=desde, hasta=hasta,
        recupero=recupero("desde", "hasta"),
        recupero_anterior=recupero("desde_ant", "hasta_ant"),
        cartera=[EstadoCartera(**r) for r in cartera],
        cuotas_atrasadas=atrasadas["n"], monto_atrasado=atrasadas["monto"],
        cuotas_vencidas_periodo=cumplimiento["vencidas"], cuotas_pagadas_periodo=cumplimiento["pagadas"],
        gestiones_periodo=gestiones, sin_gestion_30_dias=sin_gestion,
        meses=meses, por_cliente=[PorCliente(**r) for r in por_cliente],
    )

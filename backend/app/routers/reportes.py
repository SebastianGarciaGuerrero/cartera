"""
Reportes de productividad del equipo — SOLO ADMIN.

  GET /api/reportes/equipo?desde=&hasta= → por cada usuario: cuántas
      gestiones hizo (total y por tipo: llamadas, WhatsApp...), cuántos
      acuerdos creó, cuántos pagos ingresó y por qué monto.
"""

from datetime import date, datetime, time, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import require_admin
from app.models.usuario import Usuario
from app.models.gestion import Gestion, TipoGestion
from app.models.acuerdo import AcuerdoPago
from app.models.pago import Pago


router = APIRouter(
    prefix="/api/reportes",
    tags=["Reportes (admin)"],
    dependencies=[Depends(require_admin)],
)


class ReporteUsuario(BaseModel):
    usuario_id: str
    nombre: str
    activo: bool
    gestiones_total: int
    gestiones_por_tipo: dict
    acuerdos_creados: int
    pagos_ingresados: int
    monto_pagos: str


@router.get("/equipo", response_model=List[ReporteUsuario])
def reporte_equipo(
    desde: Optional[date] = Query(None, description="Desde (inclusive)"),
    hasta: Optional[date] = Query(None, description="Hasta (inclusive)"),
    db: Session = Depends(get_db),
):
    """Productividad por persona del equipo, con rango de fechas opcional."""
    # Límites del rango como datetimes con zona (las gestiones usan TIMESTAMPTZ).
    dt_desde = datetime.combine(desde, time.min, tzinfo=timezone.utc) if desde else None
    dt_hasta = datetime.combine(hasta, time.max, tzinfo=timezone.utc) if hasta else None

    # Gestiones por usuario y tipo.
    q = (
        db.query(Gestion.usuario_id, TipoGestion.nombre, func.count(Gestion.id))
        .outerjoin(TipoGestion, Gestion.tipo_id == TipoGestion.id)
    )
    if dt_desde is not None:
        q = q.filter(Gestion.fecha_gestion >= dt_desde)
    if dt_hasta is not None:
        q = q.filter(Gestion.fecha_gestion <= dt_hasta)
    gestiones = q.group_by(Gestion.usuario_id, TipoGestion.nombre).all()

    # Acuerdos por usuario.
    q = db.query(AcuerdoPago.usuario_id, func.count(AcuerdoPago.id))
    if desde is not None:
        q = q.filter(AcuerdoPago.fecha_acuerdo >= desde)
    if hasta is not None:
        q = q.filter(AcuerdoPago.fecha_acuerdo <= hasta)
    acuerdos = dict(q.group_by(AcuerdoPago.usuario_id).all())

    # Pagos por usuario (cantidad y monto).
    q = db.query(Pago.usuario_id, func.count(Pago.id), func.coalesce(func.sum(Pago.monto), 0)).filter(Pago.anulado_at.is_(None))
    if desde is not None:
        q = q.filter(Pago.fecha_pago >= desde)
    if hasta is not None:
        q = q.filter(Pago.fecha_pago <= hasta)
    pagos = {u: (n, m) for u, n, m in q.group_by(Pago.usuario_id).all()}

    # Armar el reporte por usuario.
    por_usuario: dict = {}
    for usuario_id, tipo, cantidad in gestiones:
        d = por_usuario.setdefault(usuario_id, {})
        d[tipo or "Sin tipo"] = cantidad

    usuarios = db.query(Usuario).order_by(Usuario.nombre).all()
    reporte = []
    for u in usuarios:
        tipos = por_usuario.get(u.id, {})
        n_pagos, monto = pagos.get(u.id, (0, 0))
        reporte.append(ReporteUsuario(
            usuario_id=str(u.id),
            nombre=u.nombre,
            activo=u.activo,
            gestiones_total=sum(tipos.values()),
            gestiones_por_tipo=tipos,
            acuerdos_creados=acuerdos.get(u.id, 0),
            pagos_ingresados=n_pagos,
            monto_pagos=str(monto),
        ))
    return reporte

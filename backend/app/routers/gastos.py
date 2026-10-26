"""
Gastos que paga el estudio por un caso (receptor, notificaciones, embargo,
conservador…) y que después le cobra al mandante.

Ciclo de un gasto:  por_rendir → rendido (va en una rendición al cliente)
                    → reembolsado (el cliente lo devolvió).
También: no_reembolsable (lo absorbe el estudio) y anulado (error de carga).

  GET  /api/gastos                          → lista (cliente, estado, causa, cobranza, fechas)
  POST /api/gastos                          → registrar gasto de una causa o cobranza
  PUT  /api/gastos/{id}                     → corregir (solo mientras está por rendir)
  GET  /api/gastos/resumen                  → lo adeudado por cada cliente
  POST /api/gastos/reembolsar               → marcar reembolsados varios gastos de una vez
  GET  /api/gastos/rendiciones              → rendiciones emitidas
  POST /api/gastos/rendiciones              → rendir los gastos elegidos (de un mismo cliente)
  GET  /api/gastos/rendiciones/{id}         → detalle
  POST /api/gastos/rendiciones/{id}/pagada  → el cliente pagó: sus gastos quedan reembolsados
  POST /api/gastos/rendiciones/{id}/anular  → anular: sus gastos vuelven a por rendir
"""

from datetime import date
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.indicadores import hoy_chile
from app.models.cobranza import Cobranza
from app.models.judicial import Causa, Gasto, RendicionGastos
from app.models.usuario import Usuario
from app.planes import requiere_funcion
from app.schemas.judicial import (
    GastoCreate, GastoResponse, GastoUpdate, PagoRendicion, ReembolsoMasivo, RendicionCreate,
    RendicionDetalle, RendicionResponse, ResumenGastosCliente,
)
from app.security import get_current_user, usuario_autorizado
from app.permisos import requiere_permiso, tiene_permiso

router = APIRouter(
    prefix="/api/gastos",
    tags=["Gastos"],
    dependencies=[Depends(usuario_autorizado), Depends(requiere_funcion("judicial"))],
)


def _gasto(db: Session, gasto_id: UUID) -> Gasto:
    gasto = db.get(Gasto, gasto_id)
    if gasto is None:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")
    return gasto


def _rendicion(db: Session, rendicion_id: UUID) -> RendicionGastos:
    r = db.get(RendicionGastos, rendicion_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Rendición no encontrada")
    return r


def _gastos_elegidos(db: Session, ids: List[UUID]) -> List[Gasto]:
    unicos = list(dict.fromkeys(ids))
    gastos = db.query(Gasto).filter(Gasto.id.in_(unicos)).all()
    if len(gastos) != len(unicos):
        raise HTTPException(status_code=404, detail="Uno de los gastos indicados no existe")
    return gastos


@router.get("/", response_model=List[GastoResponse])
def listar(
    response: Response,
    request: Request,
    cliente_id: Optional[UUID] = None,
    estado: Optional[str] = Query(None, pattern="^(por_rendir|rendido|reembolsado|no_reembolsable|anulado|adeudado)$"),
    causa_id: Optional[UUID] = None,
    cobranza_id: Optional[UUID] = None,
    rendicion_id: Optional[UUID] = None,
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=2000),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    # Sin `ver_totales`, los gastos se ven caso a caso (de una cobranza o causa).
    if not (cobranza_id or causa_id) and not tiene_permiso(request, usuario, "ver_totales"):
        raise HTTPException(status_code=403,
                            detail="Los gastos de toda la cartera los ve la administración. "
                                   "Ábrelos desde la cobranza o la causa.")
    q = db.query(Gasto).options(joinedload(Gasto.cliente), joinedload(Gasto.cobranza),
                                joinedload(Gasto.causa), joinedload(Gasto.rendicion))
    if cliente_id:
        q = q.filter(Gasto.cliente_id == cliente_id)
    if estado == "adeudado":
        q = q.filter(Gasto.estado.in_(("por_rendir", "rendido")))
    elif estado:
        q = q.filter(Gasto.estado == estado)
    if causa_id:
        q = q.filter(Gasto.causa_id == causa_id)
    if cobranza_id:
        q = q.filter(Gasto.cobranza_id == cobranza_id)
    if rendicion_id:
        q = q.filter(Gasto.rendicion_id == rendicion_id)
    if desde:
        q = q.filter(Gasto.fecha >= desde)
    if hasta:
        q = q.filter(Gasto.fecha <= hasta)
    response.headers["X-Total-Count"] = str(q.order_by(None).count())
    return q.order_by(Gasto.fecha.desc(), Gasto.created_at.desc()).offset(skip).limit(limit).all()


@router.post("/", response_model=GastoResponse, status_code=status.HTTP_201_CREATED)
def registrar(datos: GastoCreate, db: Session = Depends(get_db),
              usuario: Usuario = Depends(get_current_user)):
    if datos.causa_id is None and datos.cobranza_id is None:
        raise HTTPException(status_code=422, detail="Indique la causa o la cobranza del gasto.")
    cliente_id = None
    if datos.causa_id is not None:
        causa = db.get(Causa, datos.causa_id)
        if causa is None:
            raise HTTPException(status_code=404, detail="Causa no encontrada")
        cliente_id = causa.cliente_id
    if datos.cobranza_id is not None:
        cob = db.get(Cobranza, datos.cobranza_id)
        if cob is None:
            raise HTTPException(status_code=404, detail="Cobranza no encontrada")
        if cliente_id is not None and cob.cliente_id != cliente_id:
            raise HTTPException(status_code=400, detail="La cobranza no es del mismo cliente que la causa.")
        cliente_id = cob.cliente_id
    campos = datos.model_dump()
    campos["fecha"] = campos.get("fecha") or hoy_chile()
    gasto = Gasto(**campos, cliente_id=cliente_id, usuario_id=usuario.id)
    db.add(gasto)
    db.commit()
    db.refresh(gasto)
    return gasto


@router.put("/{gasto_id}", response_model=GastoResponse)
def corregir(gasto_id: UUID, datos: GastoUpdate, db: Session = Depends(get_db)):
    gasto = _gasto(db, gasto_id)
    if gasto.estado not in ("por_rendir", "no_reembolsable"):
        raise HTTPException(status_code=400,
                            detail="El gasto ya fue rendido al cliente: anule la rendición para corregirlo.")
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        setattr(gasto, campo, valor)
    db.commit()
    db.refresh(gasto)
    return gasto


@router.get("/resumen", response_model=List[ResumenGastosCliente], dependencies=[Depends(requiere_permiso("ver_totales"))])
def resumen(db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_user)):
    filas = db.execute(text("""
        SELECT g.cliente_id, COALESCE(cl.nombre_fantasia, cl.razon_social) AS cliente,
               COALESCE(sum(g.monto) FILTER (WHERE g.estado = 'por_rendir'), 0) AS por_rendir,
               count(*) FILTER (WHERE g.estado = 'por_rendir') AS cantidad_por_rendir,
               COALESCE(sum(g.monto) FILTER (WHERE g.estado = 'rendido'), 0) AS rendido,
               COALESCE(sum(g.monto) FILTER (WHERE g.estado = 'reembolsado'), 0) AS reembolsado
        FROM gastos g
        JOIN clientes cl ON cl.id = g.cliente_id
        WHERE g.organizacion_id = :org AND g.estado IN ('por_rendir', 'rendido', 'reembolsado')
        GROUP BY g.cliente_id, cl.nombre_fantasia, cl.razon_social
        ORDER BY (COALESCE(sum(g.monto) FILTER (WHERE g.estado IN ('por_rendir', 'rendido')), 0)) DESC
    """), {"org": usuario.organizacion_id}).mappings().all()
    return [{**f, "total_adeudado": Decimal(f["por_rendir"]) + Decimal(f["rendido"])} for f in filas]


@router.post("/reembolsar", response_model=List[GastoResponse], dependencies=[Depends(requiere_permiso("gastos_rendir"))])
def reembolsar(datos: ReembolsoMasivo, db: Session = Depends(get_db)):
    """El cliente devolvió estos gastos (rendidos o no): quedan reembolsados."""
    gastos = _gastos_elegidos(db, datos.gasto_ids)
    malos = [g for g in gastos if g.estado not in ("por_rendir", "rendido")]
    if malos:
        raise HTTPException(status_code=400,
                            detail="Solo se reembolsan gastos por rendir o rendidos.")
    fecha = datos.fecha or hoy_chile()
    for g in gastos:
        g.estado = "reembolsado"
        g.fecha_reembolso = fecha
    db.flush()
    # Una rendición queda pagada cuando todos sus gastos fueron reembolsados.
    for rid in {g.rendicion_id for g in gastos if g.rendicion_id}:
        pendientes = db.query(func.count(Gasto.id)).filter(
            Gasto.rendicion_id == rid, Gasto.estado == "rendido").scalar()
        if pendientes == 0:
            r = db.get(RendicionGastos, rid)
            r.estado = "pagada"
            r.fecha_pago = fecha
    db.commit()
    return gastos


# ------------------------------------------------------------------ rendiciones

def _con_cantidad(r: RendicionGastos) -> dict:
    datos = {c: getattr(r, c) for c in (
        "id", "numero", "cliente_id", "cliente_nombre", "fecha", "total", "estado",
        "fecha_pago", "observaciones", "created_at")}
    datos["cantidad"] = len(r.gastos)
    return datos


@router.get("/rendiciones", response_model=List[RendicionResponse], dependencies=[Depends(requiere_permiso("gastos_rendir"))])
def rendiciones(cliente_id: Optional[UUID] = None, estado: Optional[str] = None,
                limit: int = Query(200, ge=1, le=1000), db: Session = Depends(get_db)):
    q = db.query(RendicionGastos).options(joinedload(RendicionGastos.cliente),
                                          joinedload(RendicionGastos.gastos))
    if cliente_id:
        q = q.filter(RendicionGastos.cliente_id == cliente_id)
    if estado:
        q = q.filter(RendicionGastos.estado == estado)
    return [_con_cantidad(r) for r in q.order_by(RendicionGastos.numero.desc()).limit(limit).all()]


@router.post("/rendiciones", response_model=RendicionDetalle, status_code=status.HTTP_201_CREATED, dependencies=[Depends(requiere_permiso("gastos_rendir"))])
def rendir(datos: RendicionCreate, db: Session = Depends(get_db),
           usuario: Usuario = Depends(get_current_user)):
    gastos = _gastos_elegidos(db, datos.gasto_ids)
    if any(g.estado != "por_rendir" for g in gastos):
        raise HTTPException(status_code=400, detail="Solo se pueden rendir gastos que están por rendir.")
    clientes = {g.cliente_id for g in gastos}
    if len(clientes) != 1:
        raise HTTPException(status_code=400, detail="Una rendición es para un solo cliente.")
    numero = (db.query(func.coalesce(func.max(RendicionGastos.numero), 0)).scalar() or 0) + 1
    rendicion = RendicionGastos(
        numero=numero, cliente_id=clientes.pop(), fecha=datos.fecha or hoy_chile(),
        total=sum((Decimal(g.monto) for g in gastos), Decimal(0)),
        observaciones=datos.observaciones, creado_por=usuario.id,
    )
    db.add(rendicion)
    db.flush()
    for g in gastos:
        g.estado = "rendido"
        g.rendicion_id = rendicion.id
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Otra persona emitió una rendición al mismo tiempo; intente de nuevo.")
    return detalle_rendicion(rendicion.id, db)


@router.get("/rendiciones/{rendicion_id}", response_model=RendicionDetalle, dependencies=[Depends(requiere_permiso("gastos_rendir"))])
def detalle_rendicion(rendicion_id: UUID, db: Session = Depends(get_db)):
    r = _rendicion(db, rendicion_id)
    datos = _con_cantidad(r)
    datos["gastos"] = sorted(r.gastos, key=lambda g: (g.fecha, g.created_at))
    return datos


@router.post("/rendiciones/{rendicion_id}/pagada", response_model=RendicionDetalle, dependencies=[Depends(requiere_permiso("gastos_rendir"))])
def rendicion_pagada(rendicion_id: UUID, datos: PagoRendicion, db: Session = Depends(get_db)):
    r = _rendicion(db, rendicion_id)
    if r.estado != "enviada":
        raise HTTPException(status_code=400, detail="La rendición no está pendiente de pago.")
    fecha = datos.fecha_pago or hoy_chile()
    r.estado = "pagada"
    r.fecha_pago = fecha
    for g in r.gastos:
        if g.estado == "rendido":
            g.estado = "reembolsado"
            g.fecha_reembolso = fecha
    db.commit()
    return detalle_rendicion(r.id, db)


@router.post("/rendiciones/{rendicion_id}/anular", response_model=RendicionDetalle, dependencies=[Depends(requiere_permiso("gastos_rendir"))])
def anular_rendicion(rendicion_id: UUID, db: Session = Depends(get_db)):
    r = _rendicion(db, rendicion_id)
    if r.estado != "enviada":
        raise HTTPException(status_code=400, detail="Solo se anula una rendición que no ha sido pagada.")
    if any(g.estado == "reembolsado" for g in r.gastos):
        raise HTTPException(status_code=400, detail="La rendición tiene gastos ya reembolsados.")
    r.estado = "anulada"
    for g in list(r.gastos):
        g.estado = "por_rendir"
        g.rendicion_id = None
    db.commit()
    return detalle_rendicion(r.id, db)

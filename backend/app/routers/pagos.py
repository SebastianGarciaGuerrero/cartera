"""
Endpoints HTTP para pagos.

Endpoints:
  GET  /api/pagos          → listar (filtros: cobranza_id, cuota_id, rango de fechas)
  GET  /api/pagos/{id}     → obtener uno
  POST /api/pagos          → registrar un pago (con lógica de cascada)

*** Los pagos son INMUTABLES: no hay PUT ni DELETE. ***

CASCADA al registrar un pago (todo en UNA transacción):
  1. Se descuenta SOLO el capital de cobranzas.monto_actual (sin bajar de 0).
  2. Si el pago es de una cuota → se suma a cuotas.monto_pagado y se recalcula
     su estado (pagada / pagada_parcial).
  3. Si con eso TODAS las cuotas del acuerdo quedan pagadas → el acuerdo pasa
     a 'cumplido' y la cobranza a 'pagada'.
  4. Si el saldo de la cobranza llega a 0 (aunque sea pago directo sin cuota)
     → la cobranza pasa a 'pagada'.
"""

from uuid import UUID
from datetime import date
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.security import get_current_user, usuario_autorizado
from app.models.pago import Pago
from app.models.cobranza import Cobranza
from app.operaciones import registrar_pago as registrar_pago_en
from app.models.usuario import Usuario
from app.schemas.pago import PagoCreate, PagoResponse


# dependencies=[...] exige token válido en TODOS los endpoints del router
# y aplica la regla de roles (viewer = solo lectura).
router = APIRouter(
    prefix="/api/pagos",
    tags=["Pagos"],
    dependencies=[Depends(usuario_autorizado)],
)


@router.get("/", response_model=List[PagoResponse])
def listar_pagos(
    cobranza_id: Optional[UUID] = None,
    cuota_id: Optional[UUID] = None,
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """
    Lista pagos con filtros. El rango de fechas (desde/hasta) sirve para armar
    el recupero mensual.
    """
    query = db.query(Pago)
    if cobranza_id is not None:
        query = query.filter(Pago.cobranza_id == cobranza_id)
    if cuota_id is not None:
        query = query.filter(Pago.cuota_id == cuota_id)
    if desde is not None:
        query = query.filter(Pago.fecha_pago >= desde)
    if hasta is not None:
        query = query.filter(Pago.fecha_pago <= hasta)
    return query.order_by(Pago.fecha_pago.desc()).offset(skip).limit(limit).all()


@router.get("/{pago_id}", response_model=PagoResponse)
def obtener_pago(pago_id: UUID, db: Session = Depends(get_db)):
    """Obtiene un pago por su UUID."""
    pago = db.query(Pago).filter(Pago.id == pago_id).first()
    if not pago:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pago con id {pago_id} no encontrado"
        )
    return pago


@router.post("/", response_model=PagoResponse, status_code=status.HTTP_201_CREATED)
def registrar_pago(
    pago_data: PagoCreate,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """
    Registra un pago y aplica la cascada. Todo se confirma junto o nada.
    Quién lo registró (usuario_id) sale del token.
    """
    # --- Validaciones previas ---
    cobranza = db.query(Cobranza).filter(Cobranza.id == pago_data.cobranza_id).first()
    if not cobranza:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cobranza con id {pago_data.cobranza_id} no encontrada"
        )

    nuevo_pago, _ = registrar_pago_en(db, cobranza, pago_data, usuario)

    try:
        db.commit()
        db.refresh(nuevo_pago)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se pudo registrar el pago. Verifica que el usuario (usuario_id) exista."
        )

    return nuevo_pago

"""
Endpoints HTTP para acuerdos de pago.

Endpoints:
  GET  /api/acuerdos            → listar (filtrable por cobranza_id / estado)
  GET  /api/acuerdos/{id}       → detalle con el calendario de cuotas
  POST /api/acuerdos            → crear acuerdo + cuotas (automáticas o escritas a mano)
  PUT  /api/acuerdos/{id}       → cambiar SOLO estado / firma (montos inmutables)

Reglas de negocio implementadas aquí:
  - Solo puede haber UN acuerdo 'vigente' por cobranza a la vez.
  - Al crear un acuerdo, las cuotas se generan solas y la cobranza pasa a
    estado 'acuerdo_pago'.
  - Montos y cuotas son inmutables: una renegociación se hace marcando el
    acuerdo viejo como 'renegociado' (vía PUT) y creando uno nuevo.
"""

from uuid import UUID
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.security import get_current_user, usuario_autorizado
from app.models.acuerdo import AcuerdoPago
from app.models.cobranza import Cobranza
from app.operaciones import crear_acuerdo as crear_acuerdo_en
from app.operaciones import validar_sin_acuerdo_vigente  # noqa: F401 (lo importan otros módulos)
from app.models.usuario import Usuario
from app.schemas.acuerdo import (
    AcuerdoCreate,
    AcuerdoEstadoUpdate,
    AcuerdoResponse,
    AcuerdoDetalle,
)


# dependencies=[...] exige token válido en TODOS los endpoints del router
# y aplica la regla de roles (viewer = solo lectura).
router = APIRouter(
    prefix="/api/acuerdos",
    tags=["Acuerdos de pago"],
    dependencies=[Depends(usuario_autorizado)],
)


@router.get("/", response_model=List[AcuerdoResponse])
def listar_acuerdos(
    cobranza_id: Optional[UUID] = None,
    estado: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """Lista acuerdos, filtrables por cobranza y/o estado."""
    query = db.query(AcuerdoPago)
    if cobranza_id is not None:
        query = query.filter(AcuerdoPago.cobranza_id == cobranza_id)
    if estado is not None:
        query = query.filter(AcuerdoPago.estado == estado)
    return (
        query.order_by(AcuerdoPago.fecha_acuerdo.desc())
        .offset(skip).limit(limit).all()
    )


@router.get("/{acuerdo_id}", response_model=AcuerdoDetalle)
def obtener_acuerdo(acuerdo_id: UUID, db: Session = Depends(get_db)):
    """Detalle de un acuerdo con su calendario de cuotas."""
    acuerdo = db.query(AcuerdoPago).filter(AcuerdoPago.id == acuerdo_id).first()
    if not acuerdo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Acuerdo con id {acuerdo_id} no encontrado"
        )
    return acuerdo


@router.post("/", response_model=AcuerdoDetalle, status_code=status.HTTP_201_CREATED)
def crear_acuerdo(
    acuerdo_data: AcuerdoCreate,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """
    Crea un acuerdo con sus cuotas (generadas en partes iguales o escritas a
    mano en `cuotas`) y deja la cobranza en estado 'acuerdo_pago'. Rechaza
    si la cobranza ya tiene un acuerdo vigente. Quién lo registró sale del token.
    """
    cobranza = db.query(Cobranza).filter(Cobranza.id == acuerdo_data.cobranza_id).first()
    if not cobranza:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cobranza con id {acuerdo_data.cobranza_id} no encontrada"
        )
    nuevo_acuerdo, _ = crear_acuerdo_en(db, cobranza, acuerdo_data, usuario)

    try:
        db.commit()
        db.refresh(nuevo_acuerdo)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se pudo crear el acuerdo. Verifica que el usuario (usuario_id) exista."
        )

    return nuevo_acuerdo


@router.put("/{acuerdo_id}", response_model=AcuerdoResponse)
def actualizar_estado_acuerdo(
    acuerdo_id: UUID,
    datos: AcuerdoEstadoUpdate,
    db: Session = Depends(get_db)
):
    """
    Actualiza SOLO el estado, la firma del cliente y observaciones de un
    acuerdo. Los montos y las cuotas no se pueden editar (son inmutables).
    """
    acuerdo = db.query(AcuerdoPago).filter(AcuerdoPago.id == acuerdo_id).first()
    if not acuerdo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Acuerdo con id {acuerdo_id} no encontrado"
        )

    for campo, valor in datos.model_dump(exclude_unset=True).items():
        setattr(acuerdo, campo, valor)

    db.commit()
    db.refresh(acuerdo)
    return acuerdo

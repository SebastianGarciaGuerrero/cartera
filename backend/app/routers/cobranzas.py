"""
Endpoints HTTP para gestión de cobranzas (el núcleo del sistema).

Endpoints:
  GET  /api/cobranzas            → listar con paginación y filtros
  GET  /api/cobranzas/buscar     → buscar por N° de cobranza, ID cliente, RUT o nombre deudor
  GET  /api/cobranzas/{id}       → ficha completa (cliente, filial y deudor anidados)
  POST /api/cobranzas            → crear una nueva
  PUT  /api/cobranzas/{id}       → actualizar (numero, cliente_id y deudor_id NO cambian)

NO hay DELETE: una cobranza no se borra. Para "sacarla de la cartera" se
cambia su 'estado' a 'archivada' o 'castigo' vía PUT.
"""

from uuid import UUID
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query, Response
from sqlalchemy import or_, cast, String
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.security import usuario_autorizado
from app.models.cobranza import Cobranza
from app.models.deudor import Deudor
from app.schemas.cobranza import (
    CobranzaCreate,
    CobranzaUpdate,
    CobranzaResponse,
    CobranzaDetalle,
)


# dependencies=[...] exige token válido en TODOS los endpoints del router
# y aplica la regla de roles (viewer = solo lectura).
router = APIRouter(
    prefix="/api/cobranzas",
    tags=["Cobranzas"],
    dependencies=[Depends(usuario_autorizado)],
)


@router.get("/", response_model=List[CobranzaResponse])
def listar_cobranzas(
    response: Response,
    skip: int = 0,
    limit: int = 100,
    cliente_id: Optional[UUID] = None,
    filial_id: Optional[int] = None,
    ejecutivo_id: Optional[UUID] = None,
    estado: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Lista cobranzas con paginación y filtros opcionales.
    Los filtros se combinan (AND): pasar cliente_id + estado devuelve
    las cobranzas de ese cliente en ese estado.

    El total de resultados (sin paginar) va en el header X-Total-Count, para
    que el frontend pueda mostrar "página X de Y".
    """
    query = db.query(Cobranza)

    if cliente_id is not None:
        query = query.filter(Cobranza.cliente_id == cliente_id)
    if filial_id is not None:
        query = query.filter(Cobranza.filial_id == filial_id)
    if ejecutivo_id is not None:
        query = query.filter(Cobranza.ejecutivo_id == ejecutivo_id)
    if estado is not None:
        query = query.filter(Cobranza.estado == estado)

    response.headers["X-Total-Count"] = str(query.count())
    return query.order_by(Cobranza.numero).offset(skip).limit(limit).all()


@router.get("/buscar", response_model=List[CobranzaResponse])
def buscar_cobranzas(
    q: str = Query(..., min_length=1, description="N° de cobranza, ID cliente, RUT o nombre del deudor"),
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """
    Busca cobranzas por N° de cobranza (coincidencia parcial: '2000'
    encuentra la 20001), ID cliente, o RUT/nombre del deudor.
    """
    patron = f"%{q}%"
    # join con Deudor para poder buscar por RUT o nombre del deudor
    query = db.query(Cobranza).join(Deudor, Cobranza.deudor_id == Deudor.id)

    condiciones = [
        cast(Cobranza.numero, String).like(patron),
        Cobranza.id_externo.ilike(patron),
        Deudor.rut.ilike(patron),
        Deudor.nombre.ilike(patron),
    ]

    return query.filter(or_(*condiciones)).limit(limit).all()


@router.get("/{cobranza_id}", response_model=CobranzaDetalle)
def obtener_cobranza(cobranza_id: UUID, db: Session = Depends(get_db)):
    """Ficha completa de una cobranza, con cliente, filial y deudor anidados."""
    cobranza = db.query(Cobranza).filter(Cobranza.id == cobranza_id).first()

    if not cobranza:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cobranza con id {cobranza_id} no encontrada"
        )

    return cobranza


@router.post("/", response_model=CobranzaResponse, status_code=status.HTTP_201_CREATED)
def crear_cobranza(cobranza_data: CobranzaCreate, db: Session = Depends(get_db)):
    """
    Crea una cobranza nueva.
    - El N° de cobranza lo asigna PostgreSQL automáticamente.
    - monto_actual se inicializa igual a monto_original.
    - Si id_externo ya existe para ese cliente, devuelve error 400.
    """
    datos = cobranza_data.model_dump()
    # Regla de negocio: al crear, el saldo actual = la deuda original.
    datos["monto_actual"] = datos["monto_original"]

    nueva_cobranza = Cobranza(**datos)

    try:
        db.add(nueva_cobranza)
        db.commit()
        db.refresh(nueva_cobranza)  # trae el numero generado por PostgreSQL
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No se pudo crear la cobranza. Verifica que el cliente y el "
                "deudor existan y que el ID externo no esté repetido para ese cliente."
            )
        )

    return nueva_cobranza


@router.put("/{cobranza_id}", response_model=CobranzaResponse)
def actualizar_cobranza(
    cobranza_id: UUID,
    cobranza_data: CobranzaUpdate,
    db: Session = Depends(get_db)
):
    """
    Actualiza una cobranza. El N° de cobranza, el cliente y el deudor NO se pueden
    cambiar (no están en CobranzaUpdate). Aquí se cambia el estado.
    """
    cobranza = db.query(Cobranza).filter(Cobranza.id == cobranza_id).first()

    if not cobranza:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cobranza con id {cobranza_id} no encontrada"
        )

    datos_actualizados = cobranza_data.model_dump(exclude_unset=True)
    for campo, valor in datos_actualizados.items():
        setattr(cobranza, campo, valor)

    try:
        db.commit()
        db.refresh(cobranza)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se pudo actualizar: posible ID externo repetido para el cliente."
        )

    return cobranza

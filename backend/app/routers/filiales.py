"""
Endpoints para gestión de filiales (sucursales de un cliente).
"""

from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.models.filial import Filial
from app.models.cliente import Cliente
from app.schemas.filial import FilialCreate, FilialUpdate, FilialResponse, FilialConCliente
from app.security import usuario_autorizado
from app.permisos import requiere_permiso


# dependencies=[...] exige token válido en TODOS los endpoints del router
# y aplica la regla de roles (viewer = solo lectura).
router = APIRouter(
    prefix="/api/filiales",
    tags=["Filiales"],
    dependencies=[Depends(usuario_autorizado)],
)


@router.get("/", response_model=List[FilialConCliente])
def listar_filiales(
    cliente_id: UUID = Query(None, description="Filtrar por cliente"),
    solo_activas: bool = True,
    db: Session = Depends(get_db)
):
    """
    Lista todas las filiales, opcionalmente filtradas por cliente.
    
    - **cliente_id**: si se envía, devuelve solo las filiales de ese cliente
    - **solo_activas**: si es True, oculta las desactivadas
    """
    query = db.query(Filial).join(Cliente)
    
    if cliente_id:
        query = query.filter(Filial.cliente_id == cliente_id)
    
    if solo_activas:
        query = query.filter(Filial.activo == True)
    
    filiales = query.order_by(Cliente.razon_social, Filial.nombre).all()
    
    # Enriquecer cada filial con datos del cliente
    resultado = []
    for f in filiales:
        resultado.append(FilialConCliente(
            id=f.id,
            cliente_id=f.cliente_id,
            nombre=f.nombre,
            activo=f.activo,
            created_at=f.created_at,
            cliente_razon_social=f.cliente.razon_social,
            cliente_rut=f.cliente.rut
        ))
    
    return resultado


@router.get("/{filial_id}", response_model=FilialResponse)
def obtener_filial(filial_id: int, db: Session = Depends(get_db)):
    """Obtiene una filial por su ID."""
    filial = db.query(Filial).filter(Filial.id == filial_id).first()
    
    if not filial:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Filial con id {filial_id} no encontrada"
        )
    
    return filial


@router.post("/", response_model=FilialResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(requiere_permiso("clientes_editar"))])
def crear_filial(filial_data: FilialCreate, db: Session = Depends(get_db)):
    """
    Crea una filial nueva para un cliente existente.
    Errores:
    - 404 si el cliente no existe
    - 400 si ya existe una filial con ese nombre en el cliente
    """
    # Verificar que el cliente existe
    cliente = db.query(Cliente).filter(Cliente.id == filial_data.cliente_id).first()
    if not cliente:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cliente con id {filial_data.cliente_id} no encontrado"
        )
    
    nueva_filial = Filial(**filial_data.model_dump())
    
    try:
        db.add(nueva_filial)
        db.commit()
        db.refresh(nueva_filial)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ya existe una filial '{filial_data.nombre}' en el cliente {cliente.razon_social}"
        )
    
    return nueva_filial


@router.put("/{filial_id}", response_model=FilialResponse, dependencies=[Depends(requiere_permiso("clientes_editar"))])
def actualizar_filial(
    filial_id: int,
    filial_data: FilialUpdate,
    db: Session = Depends(get_db)
):
    """Actualiza nombre o estado de una filial."""
    filial = db.query(Filial).filter(Filial.id == filial_id).first()
    
    if not filial:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Filial con id {filial_id} no encontrada"
        )
    
    datos = filial_data.model_dump(exclude_unset=True)
    for campo, valor in datos.items():
        setattr(filial, campo, valor)
    
    try:
        db.commit()
        db.refresh(filial)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Conflicto: ya existe una filial con ese nombre en este cliente"
        )
    
    return filial


@router.delete("/{filial_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(requiere_permiso("clientes_editar"))])
def desactivar_filial(filial_id: int, db: Session = Depends(get_db)):
    """Desactiva una filial (soft delete)."""
    filial = db.query(Filial).filter(Filial.id == filial_id).first()
    
    if not filial:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Filial con id {filial_id} no encontrada"
        )
    
    filial.activo = False
    db.commit()
    return None
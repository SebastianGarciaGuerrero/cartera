"""
Endpoints HTTP para gestión de clientes.

Endpoints:
  GET    /api/clientes          → listar todos
  GET    /api/clientes/{id}     → obtener uno por ID
  POST   /api/clientes          → crear uno nuevo
  PUT    /api/clientes/{id}     → actualizar uno existente
  DELETE /api/clientes/{id}     → desactivar (soft delete)
"""

from uuid import UUID
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.models.cliente import Cliente
from app.schemas.cliente import ClienteCreate, ClienteUpdate, ClienteResponse
from app.security import usuario_autorizado
from app.permisos import requiere_permiso


# Router agrupa endpoints relacionados.
# prefix="/api/clientes" se agrega a todas las rutas de este router.
# tags=["Clientes"] agrupa los endpoints en la documentación /docs
# dependencies=[...] exige token válido en TODOS los endpoints del router
# y aplica la regla de roles (viewer = solo lectura).
router = APIRouter(
    prefix="/api/clientes",
    tags=["Clientes"],
    dependencies=[Depends(usuario_autorizado)],
)


@router.get("/", response_model=List[ClienteResponse])
def listar_clientes(
    skip: int = 0,
    limit: int = 100,
    solo_activos: bool = True,
    db: Session = Depends(get_db)
):
    """
    Lista todos los clientes con paginación.
    
    - **skip**: cuántos saltar (para paginación)
    - **limit**: cuántos devolver (máximo 100)
    - **solo_activos**: si es True, no muestra los desactivados
    """
    query = db.query(Cliente)
    
    if solo_activos:
        query = query.filter(Cliente.activo == True)
    
    clientes = query.offset(skip).limit(limit).all()
    return clientes


@router.get("/{cliente_id}", response_model=ClienteResponse)
def obtener_cliente(cliente_id: UUID, db: Session = Depends(get_db)):
    """Obtiene un cliente específico por su UUID."""
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    
    if not cliente:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cliente con id {cliente_id} no encontrado"
        )
    
    return cliente


@router.post("/", response_model=ClienteResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(requiere_permiso("clientes_editar"))])
def crear_cliente(cliente_data: ClienteCreate, db: Session = Depends(get_db)):
    """
    Crea un cliente nuevo.
    Si ya existe un cliente con el mismo RUT, devuelve error 400.
    """
    # Crear instancia del modelo con los datos recibidos
    nuevo_cliente = Cliente(**cliente_data.model_dump())
    
    try:
        db.add(nuevo_cliente)
        db.commit()
        db.refresh(nuevo_cliente)  # Refresca para obtener los valores generados (id, timestamps)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ya existe un cliente con RUT {cliente_data.rut}"
        )
    
    return nuevo_cliente


@router.put("/{cliente_id}", response_model=ClienteResponse, dependencies=[Depends(requiere_permiso("clientes_editar"))])
def actualizar_cliente(
    cliente_id: UUID,
    cliente_data: ClienteUpdate,
    db: Session = Depends(get_db)
):
    """Actualiza los datos de un cliente existente."""
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    
    if not cliente:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cliente con id {cliente_id} no encontrado"
        )
    
    # exclude_unset=True hace que solo actualice los campos que el usuario envió
    datos_actualizados = cliente_data.model_dump(exclude_unset=True)
    
    for campo, valor in datos_actualizados.items():
        setattr(cliente, campo, valor)
    
    db.commit()
    db.refresh(cliente)
    return cliente


@router.delete("/{cliente_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(requiere_permiso("clientes_editar"))])
def desactivar_cliente(cliente_id: UUID, db: Session = Depends(get_db)):
    """
    Desactiva un cliente (soft delete).
    No se borra de la base de datos, solo se marca como inactivo.
    Esto preserva el historial de cobranzas vinculadas.
    """
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    
    if not cliente:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cliente con id {cliente_id} no encontrado"
        )
    
    cliente.activo = False
    db.commit()
    return None
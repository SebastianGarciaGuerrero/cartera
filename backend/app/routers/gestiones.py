"""
Endpoints HTTP para gestiones (el historial de acciones, INMUTABLE).

Endpoints:
  GET  /api/gestiones/tipos      → catálogo de tipos de gestión (para selects)
  GET  /api/gestiones            → listar (normalmente filtrado por cobranza_id)
  GET  /api/gestiones/{id}       → obtener una, con su tipo anidado
  POST /api/gestiones            → registrar una gestión nueva

*** NO hay PUT ni DELETE: las gestiones son inmutables. ***
Si una gestión quedó mal, se registra una gestión correctiva nueva.
"""

from uuid import UUID
from typing import List, Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.security import get_current_user, require_admin, usuario_autorizado
from app.models.gestion import Gestion, TipoGestion
from app.models.cobranza import Cobranza
from app.models.usuario import Usuario
from app.schemas.gestion import (
    GestionCreate,
    GestionResponse,
    GestionDetalle,
    TipoGestionResponse,
)


# dependencies=[...] exige token válido en TODOS los endpoints del router
# y aplica la regla de roles (viewer = solo lectura).
router = APIRouter(
    prefix="/api/gestiones",
    tags=["Gestiones"],
    dependencies=[Depends(usuario_autorizado)],
)


@router.get("/tipos", response_model=List[TipoGestionResponse])
def listar_tipos_gestion(
    solo_activos: bool = True,
    db: Session = Depends(get_db)
):
    """
    Tipos de gestión: los de sistema más los propios de la organización
    (el filtro lo pone app/tenancy.py).
    """
    query = db.query(TipoGestion)
    if solo_activos:
        query = query.filter(TipoGestion.activo.is_(True))
    return query.order_by(TipoGestion.nombre).all()


class TipoGestionEntrada(BaseModel):
    nombre: str = Field(..., min_length=2, max_length=100)
    categoria: Literal["contacto", "pago", "negativo", "judicial", "otro"] = "otro"
    activo: bool = True


@router.post("/tipos", response_model=TipoGestionResponse, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_admin)])
def crear_tipo_gestion(datos: TipoGestionEntrada, db: Session = Depends(get_db)):
    """Tipo de gestión propio del estudio (ej. 'Visita notario')."""
    tipo = TipoGestion(**datos.model_dump())
    try:
        db.add(tipo)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Ya existe un tipo con ese nombre.")
    db.refresh(tipo)
    return tipo


@router.put("/tipos/{tipo_id}", response_model=TipoGestionResponse,
            dependencies=[Depends(require_admin)])
def editar_tipo_gestion(tipo_id: int, datos: TipoGestionEntrada, db: Session = Depends(get_db)):
    """Solo los tipos propios se editan; los de sistema son fijos."""
    tipo = db.get(TipoGestion, tipo_id)
    if tipo is None or not tipo.propio:
        raise HTTPException(status_code=404, detail="Tipo no encontrado o es de sistema.")
    for k, v in datos.model_dump().items():
        setattr(tipo, k, v)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Ya existe un tipo con ese nombre.")
    db.refresh(tipo)
    return tipo


@router.get("/", response_model=List[GestionResponse])
def listar_gestiones(
    cobranza_id: Optional[UUID] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db)
):
    """
    Lista gestiones, normalmente filtradas por cobranza (su historial).
    Ordena de la más reciente a la más antigua.
    """
    query = db.query(Gestion)
    if cobranza_id is not None:
        query = query.filter(Gestion.cobranza_id == cobranza_id)
    return (
        query.order_by(Gestion.fecha_gestion.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.get("/{gestion_id}", response_model=GestionDetalle)
def obtener_gestion(gestion_id: UUID, db: Session = Depends(get_db)):
    """Obtiene una gestión por su UUID, con el tipo anidado."""
    gestion = db.get(Gestion, gestion_id)

    if not gestion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Gestión con id {gestion_id} no encontrada"
        )

    return gestion


@router.post("/", response_model=GestionResponse, status_code=status.HTTP_201_CREATED)
def crear_gestion(
    gestion_data: GestionCreate,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """
    Registra una gestión nueva (única operación de escritura permitida).
    Quién la registró (usuario_id) sale del TOKEN, no del payload: nadie
    puede atribuirle una gestión a otra persona.
    """
    # Validar que la cobranza referenciada exista (404 explícito).
    cobranza = db.get(Cobranza, gestion_data.cobranza_id)
    if not cobranza:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cobranza con id {gestion_data.cobranza_id} no encontrada"
        )
    if gestion_data.tipo_id is not None and db.get(TipoGestion, gestion_data.tipo_id) is None:
        raise HTTPException(status_code=404, detail="El tipo de gestión no existe")

    # exclude_unset para que, si no envían fecha_gestion, PostgreSQL ponga NOW().
    nueva_gestion = Gestion(
        **gestion_data.model_dump(exclude_unset=True),
        usuario_id=usuario.id,  # ← del token, firmado; no falsificable
    )

    try:
        db.add(nueva_gestion)
        db.commit()
        db.refresh(nueva_gestion)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No se pudo registrar la gestión. Verifica que el usuario "
                "(usuario_id) y el tipo (tipo_id) existan."
            )
        )

    return nueva_gestion

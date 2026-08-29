"""
Datos de la empresa que usa el sistema (Configuración → Mi empresa).

  GET /api/empresa  → los lee cualquier usuario autenticado (la barra lateral
                      y los documentos Word necesitan el nombre y el membrete).
  PUT /api/empresa  → los edita SOLO el admin.

Es una fila única (id = 1) creada por el DDL: no hay POST ni DELETE.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.empresa import Empresa
from app.models.usuario import Usuario
from app.security import get_current_user, require_admin
from app.schemas.empresa import EmpresaUpdate, EmpresaResponse


router = APIRouter(
    prefix="/api/empresa",
    tags=["Mi empresa"],
)

EMPRESA_ID = 1


def obtener_empresa(db: Session) -> Empresa:
    """
    Devuelve la fila única. Si falta (base creada con un DDL viejo), avisa
    claro en vez de reventar con un AttributeError más adelante.
    """
    empresa = db.query(Empresa).filter(Empresa.id == EMPRESA_ID).first()
    if empresa is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No hay datos de empresa cargados. Revisa que la migración "
                   "de la tabla 'empresa' se haya ejecutado.",
        )
    return empresa


@router.get("", response_model=EmpresaResponse)
def ver_empresa(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Datos de la empresa. Los lee cualquier usuario con sesión iniciada."""
    return obtener_empresa(db)


@router.put("", response_model=EmpresaResponse)
def actualizar_empresa(
    datos: EmpresaUpdate,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """
    Actualiza los datos de la empresa. Solo admin: cambia el membrete de todos
    los documentos que salen del sistema.
    """
    empresa = obtener_empresa(db)

    # exclude_unset: solo tocamos los campos que la pantalla mandó.
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        setattr(empresa, campo, valor)

    db.commit()
    db.refresh(empresa)
    return empresa

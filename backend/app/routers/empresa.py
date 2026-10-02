"""
Datos institucionales de la organización (Configuración → Mi empresa).

  GET /api/empresa  → los lee cualquier usuario autenticado (la barra lateral
                      y los documentos Word necesitan el nombre y el membrete).
  PUT /api/empresa  → los edita SOLO el admin. Si la organización todavía no
                      los tenía cargados, se crean (upsert).

Una fila por organización: el filtro lo pone app/tenancy.py, así que cada
estudio ve y edita solo la suya.
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


def obtener_empresa(db: Session) -> Empresa | None:
    return db.query(Empresa).first()


@router.get("", response_model=EmpresaResponse)
def ver_empresa(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Datos de la empresa. Los lee cualquier usuario con sesión iniciada."""
    empresa = obtener_empresa(db)
    if empresa is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Todavía no se cargan los datos de la empresa (Configuración → Mi empresa).",
        )
    return empresa


@router.put("", response_model=EmpresaResponse)
def actualizar_empresa(
    datos: EmpresaUpdate,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """
    Actualiza (o crea la primera vez) los datos de la empresa. Solo admin:
    cambia el membrete de todos los documentos que salen del sistema.
    """
    cambios = datos.model_dump(exclude_unset=True)
    empresa = obtener_empresa(db)
    if empresa is None:
        if not cambios.get("razon_social") or not cambios.get("wordmark"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Para la primera carga indica al menos la razón social y el membrete.",
            )
        empresa = Empresa(organizacion_id=admin.organizacion_id, **cambios)
        db.add(empresa)
    else:
        for campo, valor in cambios.items():
            setattr(empresa, campo, valor)

    db.commit()
    db.refresh(empresa)
    return empresa

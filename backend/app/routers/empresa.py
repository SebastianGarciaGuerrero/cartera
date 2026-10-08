"""
Datos institucionales de la organización (Configuración → Mi empresa).

  GET /api/empresa  → los lee cualquier usuario autenticado (la barra lateral
                      y los documentos Word necesitan el nombre y el membrete).
  PUT /api/empresa  → los edita SOLO el admin. Si la organización todavía no
                      los tenía cargados, se crean (upsert).

Una fila por organización: el filtro lo pone app/tenancy.py, así que cada
estudio ve y edita solo la suya.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy.orm import Session, undefer

from app.database import get_db
from app.logos import ErrorLogo, TAMANO_MAXIMO, validar_logo
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


# ------------------------------------------------------------ logo
# GET    /api/empresa/logo → la imagen (cualquier usuario con sesión)
# PUT    /api/empresa/logo → subir o reemplazar (admin; PNG/JPG, máx. 1 MB)
# DELETE /api/empresa/logo → quitarlo (vuelve el recuadro "logo de la empresa")

@router.get("/logo")
def ver_logo(db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_user)):
    empresa = db.query(Empresa).options(undefer(Empresa.logo)).first()
    if empresa is None or not empresa.logo:
        raise HTTPException(status_code=404, detail="La empresa no tiene logo cargado.")
    return Response(
        content=empresa.logo, media_type=empresa.logo_tipo,
        headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"},
    )


@router.put("/logo", response_model=EmpresaResponse)
async def subir_logo(
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    datos = await archivo.read(TAMANO_MAXIMO + 1)
    try:
        tipo = validar_logo(datos)
    except ErrorLogo as e:
        raise HTTPException(status_code=422, detail=str(e))
    empresa = obtener_empresa(db)
    if empresa is None:
        raise HTTPException(status_code=409, detail="Primero completa los datos de Mi empresa.")
    empresa.logo, empresa.logo_tipo = datos, tipo
    empresa.logo_actualizado_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(empresa)
    return empresa


@router.delete("/logo", response_model=EmpresaResponse)
def quitar_logo(db: Session = Depends(get_db), admin: Usuario = Depends(require_admin)):
    empresa = obtener_empresa(db)
    if empresa is None:
        raise HTTPException(status_code=404, detail="No hay datos de empresa.")
    empresa.logo, empresa.logo_tipo, empresa.logo_actualizado_at = None, None, None
    db.commit()
    db.refresh(empresa)
    return empresa

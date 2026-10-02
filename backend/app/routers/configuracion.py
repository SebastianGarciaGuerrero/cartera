"""
Configuración propia de cada organización: lo que cada estudio adapta solo,
sin pedir cambios de código.

  GET  /api/organizacion            → nombre, plan, funciones y etiquetas
  PUT  /api/organizacion            → (admin) nombre y etiquetas de la interfaz
  GET  /api/campos                  → campos personalizados (filtrables)
  POST /api/campos                  → (admin) crear campo
  PUT  /api/campos/{id}             → (admin) editar / desactivar campo

Etiquetas: cómo llama cada estudio a las cosas. Un estudio dice "Mandante"
donde otro dice "Cliente"; "Sucursal" en vez de "Filial"; "N° operación"
en vez de "ID cliente". La interfaz usa estas etiquetas.
"""

import re
import unicodedata
from typing import List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.campos import campos_aplicables
from app.database import get_db
from app.models.campo_personalizado import CampoPersonalizado
from app.models.cliente import Cliente
from app.models.organizacion import Organizacion
from app.planes import funciones_de
from app.security import require_admin, usuario_autorizado

router = APIRouter(tags=["Configuración"])

# Etiquetas que la interfaz permite renombrar (clave → texto por defecto).
ETIQUETAS_DEFECTO = {
    "cliente": "Cliente",
    "clientes": "Clientes",
    "filial": "Filial",
    "filiales": "Filiales",
    "deudor": "Deudor",
    "deudores": "Deudores",
    "cobranza": "Cobranza",
    "cobranzas": "Cobranzas",
    "id_externo": "ID cliente",
    "numero_operacion": "N° operación",
    "ejecutivo": "Ejecutivo",
    "fecha_origen": "Fecha de origen",
}


class OrganizacionVista(BaseModel):
    id: UUID
    nombre: str
    slug: str
    plan: str
    estado: str
    funciones: List[str]
    etiquetas: dict


class OrganizacionCambios(BaseModel):
    nombre: Optional[str] = Field(None, min_length=2, max_length=200)
    etiquetas: Optional[dict] = None


def _vista(org: Organizacion) -> OrganizacionVista:
    etiquetas = dict(ETIQUETAS_DEFECTO)
    etiquetas.update((org.configuracion or {}).get("etiquetas") or {})
    return OrganizacionVista(
        id=org.id, nombre=org.nombre, slug=org.slug, plan=org.plan, estado=org.estado,
        funciones=sorted(funciones_de(org)), etiquetas=etiquetas,
    )


@router.get("/api/organizacion", response_model=OrganizacionVista,
            dependencies=[Depends(usuario_autorizado)])
def ver_organizacion(request: Request):
    return _vista(request.state.organizacion)


@router.put("/api/organizacion", response_model=OrganizacionVista)
def actualizar_organizacion(
    cambios: OrganizacionCambios,
    request: Request,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    org = db.get(Organizacion, request.state.organizacion.id)
    if cambios.nombre is not None:
        org.nombre = cambios.nombre
    if cambios.etiquetas is not None:
        limpias = {}
        for clave, valor in cambios.etiquetas.items():
            if clave not in ETIQUETAS_DEFECTO:
                raise HTTPException(status_code=422, detail=f"Etiqueta desconocida: {clave}")
            texto = str(valor or "").strip()[:40]
            if texto and texto != ETIQUETAS_DEFECTO[clave]:
                limpias[clave] = texto
        configuracion = dict(org.configuracion or {})
        configuracion["etiquetas"] = limpias
        org.configuracion = configuracion  # reasignar: JSONB no detecta mutaciones
    db.commit()
    db.refresh(org)
    return _vista(org)


# ============================================================
# Campos personalizados
# ============================================================

class CampoBase(BaseModel):
    etiqueta: str = Field(..., min_length=1, max_length=100)
    tipo: Literal["texto", "numero", "monto", "fecha", "seleccion", "si_no"] = "texto"
    opciones: List[str] = Field(default_factory=list)
    cliente_id: Optional[UUID] = None
    obligatorio: bool = False
    orden: int = 0


class CampoCrear(CampoBase):
    entidad: Literal["cobranza", "deudor"]
    clave: Optional[str] = Field(None, max_length=50)


class CampoEditar(BaseModel):
    etiqueta: Optional[str] = Field(None, min_length=1, max_length=100)
    opciones: Optional[List[str]] = None
    cliente_id: Optional[UUID] = None
    obligatorio: Optional[bool] = None
    orden: Optional[int] = None
    activo: Optional[bool] = None


class CampoVista(CampoBase):
    id: UUID
    entidad: str
    clave: str
    activo: bool

    model_config = ConfigDict(from_attributes=True)


def _clave_desde(etiqueta: str) -> str:
    t = unicodedata.normalize("NFKD", etiqueta).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9]+", "_", t).strip("_")
    if not t or not t[0].isalpha():
        t = f"campo_{t}" if t else "campo"
    return t[:50]


def _validar_opciones(tipo: str, opciones: List[str]) -> List[str]:
    limpias = [o.strip() for o in opciones if o and o.strip()]
    if tipo == "seleccion" and len(limpias) < 2:
        raise HTTPException(status_code=422, detail="Un campo de selección necesita al menos 2 opciones.")
    return limpias if tipo == "seleccion" else []


@router.get("/api/campos", response_model=List[CampoVista],
            dependencies=[Depends(usuario_autorizado)])
def listar_campos(
    entidad: Optional[Literal["cobranza", "deudor"]] = None,
    cliente_id: Optional[UUID] = Query(None, description="Solo los que aplican a este cliente"),
    incluir_inactivos: bool = False,
    db: Session = Depends(get_db),
):
    if cliente_id is not None and entidad is not None and not incluir_inactivos:
        return campos_aplicables(db, entidad, cliente_id)
    q = db.query(CampoPersonalizado)
    if entidad:
        q = q.filter(CampoPersonalizado.entidad == entidad)
    if not incluir_inactivos:
        q = q.filter(CampoPersonalizado.activo.is_(True))
    return q.order_by(CampoPersonalizado.entidad, CampoPersonalizado.orden,
                      CampoPersonalizado.etiqueta).all()


@router.post("/api/campos", response_model=CampoVista, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_admin)])
def crear_campo(datos: CampoCrear, db: Session = Depends(get_db)):
    if datos.cliente_id is not None and db.get(Cliente, datos.cliente_id) is None:
        raise HTTPException(status_code=404, detail="El cliente indicado no existe")
    clave = datos.clave or _clave_desde(datos.etiqueta)
    if not re.fullmatch(r"[a-z][a-z0-9_]*", clave):
        raise HTTPException(status_code=422, detail="La clave solo admite minúsculas, números y _")
    campo = CampoPersonalizado(
        entidad=datos.entidad, clave=clave, etiqueta=datos.etiqueta, tipo=datos.tipo,
        opciones=_validar_opciones(datos.tipo, datos.opciones), cliente_id=datos.cliente_id,
        obligatorio=datos.obligatorio, orden=datos.orden,
    )
    try:
        db.add(campo)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Ya existe un campo con la clave '{clave}'.")
    db.refresh(campo)
    return campo


@router.put("/api/campos/{campo_id}", response_model=CampoVista,
            dependencies=[Depends(require_admin)])
def editar_campo(campo_id: UUID, datos: CampoEditar, db: Session = Depends(get_db)):
    """El tipo y la clave no cambian (romperían los valores ya guardados)."""
    campo = db.get(CampoPersonalizado, campo_id)
    if campo is None:
        raise HTTPException(status_code=404, detail="Campo no encontrado")
    cambios = datos.model_dump(exclude_unset=True)
    if "opciones" in cambios:
        cambios["opciones"] = _validar_opciones(campo.tipo, cambios["opciones"] or [])
    if cambios.get("cliente_id") is not None and db.get(Cliente, cambios["cliente_id"]) is None:
        raise HTTPException(status_code=404, detail="El cliente indicado no existe")
    for k, v in cambios.items():
        setattr(campo, k, v)
    db.commit()
    db.refresh(campo)
    return campo

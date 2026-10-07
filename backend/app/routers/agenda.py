"""
Agenda y recordatorios.

  GET  /api/agenda?desde=&hasta=&usuario_id=&todos=  → ítems del rango
  GET  /api/agenda/hoy                               → hoy + lo atrasado (últimos 60 días)
  GET  /api/recordatorios?cobranza_id=               → recordatorios (de una cobranza)
  POST /api/recordatorios                            → anotar un recordatorio
  PUT  /api/recordatorios/{id}                       → editar / marcar hecho o descartado

Visibilidad: cada persona ve su agenda. Admin y supervisor pueden ver la
de otro (usuario_id) o la de todo el equipo (todos=true).
"""

from datetime import date, datetime, time, timedelta, timezone
from typing import List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.agenda import items_agenda
from app.database import get_db
from app.indicadores import hoy_chile
from app.models.agenda import Recordatorio
from app.models.cobranza import Cobranza
from app.models.usuario import Usuario
from app.security import get_current_user, usuario_autorizado

router = APIRouter(tags=["Agenda"], dependencies=[Depends(usuario_autorizado)])

VEN_TODO = {"admin", "supervisor"}


class ItemVista(BaseModel):
    tipo: str
    fecha: date
    titulo: str
    detalle: Optional[str] = None
    hora: Optional[time] = None
    atrasado: bool
    cobranza_id: Optional[UUID] = None
    numero_cobranza: Optional[int] = None
    deudor: Optional[str] = None
    monto: Optional[float] = None
    responsable_id: Optional[UUID] = None
    recordatorio_id: Optional[UUID] = None
    cuota_id: Optional[UUID] = None


def _usuario_objetivo(usuario: Usuario, usuario_id: Optional[UUID], todos: bool) -> Optional[UUID]:
    """None = todo el equipo."""
    if usuario.rol_nombre in VEN_TODO:
        if todos:
            return None
        return usuario_id or usuario.id
    if (usuario_id and usuario_id != usuario.id) or todos:
        raise HTTPException(status_code=403, detail="Solo puedes ver tu propia agenda.")
    return usuario.id


@router.get("/api/agenda", response_model=List[ItemVista])
def ver_agenda(
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    usuario_id: Optional[UUID] = None,
    todos: bool = False,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    hoy = hoy_chile()
    desde = desde or hoy.replace(day=1)
    hasta = hasta or (desde + timedelta(days=41))
    if hasta < desde or (hasta - desde).days > 100:
        raise HTTPException(status_code=422, detail="El rango debe ser de hasta 100 días.")
    objetivo = _usuario_objetivo(usuario, usuario_id, todos)
    return [i.dict() for i in items_agenda(db, usuario.organizacion_id, desde, hasta, objetivo, hoy)]


@router.get("/api/agenda/hoy", response_model=List[ItemVista])
def agenda_de_hoy(
    usuario_id: Optional[UUID] = None,
    todos: bool = False,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Lo de hoy más lo atrasado de los últimos 60 días (lo que quedó sin hacer)."""
    hoy = hoy_chile()
    objetivo = _usuario_objetivo(usuario, usuario_id, todos)
    return [i.dict() for i in items_agenda(db, usuario.organizacion_id,
                                           hoy - timedelta(days=60), hoy, objetivo, hoy)]


# ------------------------------------------------------------ recordatorios

class RecordatorioEntrada(BaseModel):
    fecha: date
    hora: Optional[time] = None
    titulo: str = Field(..., min_length=1, max_length=200)
    nota: Optional[str] = Field(None, max_length=2000)
    cobranza_id: Optional[UUID] = None
    usuario_id: Optional[UUID] = None   # a quién se le asigna (por defecto, a mí)


class RecordatorioCambios(BaseModel):
    fecha: Optional[date] = None
    hora: Optional[time] = None
    titulo: Optional[str] = Field(None, min_length=1, max_length=200)
    nota: Optional[str] = Field(None, max_length=2000)
    estado: Optional[Literal["pendiente", "hecho", "descartado"]] = None


class RecordatorioVista(BaseModel):
    id: UUID
    usuario_id: UUID
    cobranza_id: Optional[UUID] = None
    fecha: date
    hora: Optional[time] = None
    titulo: str
    nota: Optional[str] = None
    estado: str
    completado_at: Optional[datetime] = None
    creado_por: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


@router.get("/api/recordatorios", response_model=List[RecordatorioVista])
def listar_recordatorios(
    cobranza_id: Optional[UUID] = None,
    incluir_cerrados: bool = False,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    q = db.query(Recordatorio)
    if cobranza_id is not None:
        q = q.filter(Recordatorio.cobranza_id == cobranza_id)
    elif usuario.rol_nombre not in VEN_TODO:
        q = q.filter(Recordatorio.usuario_id == usuario.id)
    if not incluir_cerrados:
        q = q.filter(Recordatorio.estado == "pendiente")
    return q.order_by(Recordatorio.fecha, Recordatorio.hora).limit(500).all()


@router.post("/api/recordatorios", response_model=RecordatorioVista, status_code=201)
def crear_recordatorio(
    datos: RecordatorioEntrada,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    asignado = datos.usuario_id or usuario.id
    if asignado != usuario.id:
        if usuario.rol_nombre not in VEN_TODO:
            raise HTTPException(status_code=403, detail="Solo puedes anotarte recordatorios a ti.")
        if db.get(Usuario, asignado) is None:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if datos.cobranza_id is not None and db.get(Cobranza, datos.cobranza_id) is None:
        raise HTTPException(status_code=404, detail="Cobranza no encontrada")
    r = Recordatorio(
        usuario_id=asignado, cobranza_id=datos.cobranza_id, fecha=datos.fecha,
        hora=datos.hora, titulo=datos.titulo, nota=datos.nota, creado_por=usuario.id,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


@router.put("/api/recordatorios/{recordatorio_id}", response_model=RecordatorioVista)
def editar_recordatorio(
    recordatorio_id: UUID,
    cambios: RecordatorioCambios,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    r = db.get(Recordatorio, recordatorio_id)
    if r is None or (usuario.rol_nombre not in VEN_TODO
                     and usuario.id not in (r.usuario_id, r.creado_por)):
        raise HTTPException(status_code=404, detail="Recordatorio no encontrado")
    datos = cambios.model_dump(exclude_unset=True)
    for campo, valor in datos.items():
        setattr(r, campo, valor)
    if "estado" in datos:
        r.completado_at = datetime.now(timezone.utc) if datos["estado"] != "pendiente" else None
    r.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(r)
    return r

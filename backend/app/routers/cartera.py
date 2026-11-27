"""
Operaciones sobre muchas cobranzas a la vez (permiso `cartera_gestionar`).

  POST /api/cartera/asignar   → asigna las cobranzas a un ejecutivo, o las
                                reparte en partes iguales entre varios
                                (lista vacía = quitar la asignación)
  GET  /api/cartera/ejecutivos → a quién se puede asignar y cuántas tiene cada uno
  POST /api/cartera/eliminar  → "eliminada de cartera": el cliente indicó que
                                ya no corresponden. Quedan en la base y en los
                                informes con ese estado; no se borran.

Las cobranzas se eligen por sus ids (las marcadas en la lista) o con un
filtro (todas las que cumplen: cliente, filial, ejecutivo, estado, etapa…).
Solo se tocan cobranzas abiertas; cada cambio queda como gestión del caso.
"""

from typing import List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import ciclo
from app.database import get_db
from app.indicadores import hoy_chile
from app.models.cobranza import Cobranza
from app.models.usuario import Usuario
from app.operaciones import ABIERTAS, registrar_cambio
from app.permisos import requiere_permiso
from app.security import usuario_autorizado

router = APIRouter(
    prefix="/api/cartera",
    tags=["Cartera"],
    dependencies=[Depends(usuario_autorizado), Depends(requiere_permiso("cartera_gestionar"))],
)

MAX_IDS = 50_000


class FiltroCartera(BaseModel):
    cliente_id: Optional[UUID] = None
    filial_id: Optional[int] = None
    ejecutivo_id: Optional[UUID] = None
    sin_ejecutivo: bool = False
    estado: Optional[str] = None
    etapa: Optional[Literal["ingreso", "extrajudicial", "para_demanda", "judicial"]] = None
    etapa_cliente: Optional[str] = Field(None, max_length=50)
    saldo_min: Optional[float] = Field(None, ge=0)
    saldo_max: Optional[float] = Field(None, ge=0)


class Seleccion(BaseModel):
    cobranza_ids: Optional[List[UUID]] = Field(None, max_length=MAX_IDS)
    filtro: Optional[FiltroCartera] = None

    @model_validator(mode="after")
    def _una_forma(self):
        if (self.cobranza_ids is None) == (self.filtro is None):
            raise ValueError("Indica las cobranzas (cobranza_ids) o un filtro, no ambos.")
        return self


class Asignacion(Seleccion):
    # Uno = todas a esa persona; varios = repartidas en partes iguales; ninguno = sin asignar.
    ejecutivo_ids: List[UUID] = Field(default_factory=list, max_length=100)


class Eliminacion(Seleccion):
    motivo: str = Field(..., min_length=3, max_length=500)


class ResultadoMasivo(BaseModel):
    seleccionadas: int
    cambiadas: int
    omitidas: int            # cerradas o que ya estaban así
    por_ejecutivo: dict = {}


def filtrar(query, f: FiltroCartera):
    """Los mismos filtros de la lista de cobranzas."""
    if f.cliente_id is not None:
        query = query.filter(Cobranza.cliente_id == f.cliente_id)
    if f.filial_id is not None:
        query = query.filter(Cobranza.filial_id == f.filial_id)
    if f.sin_ejecutivo:
        query = query.filter(Cobranza.ejecutivo_id.is_(None))
    elif f.ejecutivo_id is not None:
        query = query.filter(Cobranza.ejecutivo_id == f.ejecutivo_id)
    if f.estado is not None:
        query = query.filter(Cobranza.estado == f.estado)
    if f.etapa is not None:
        query = query.filter(Cobranza.etapa == f.etapa, Cobranza.estado.notin_(ciclo.ESTADOS_TERMINALES))
    if f.etapa_cliente is not None:
        query = query.filter(Cobranza.etapa_cobranza == f.etapa_cliente)
    if f.saldo_min is not None:
        query = query.filter(Cobranza.monto_actual >= f.saldo_min)
    if f.saldo_max is not None:
        query = query.filter(Cobranza.monto_actual <= f.saldo_max)
    return query


def _elegidas(db: Session, sel: Seleccion) -> list[Cobranza]:
    query = db.query(Cobranza)
    if sel.cobranza_ids is not None:
        query = query.filter(Cobranza.id.in_(sel.cobranza_ids))
    else:
        query = filtrar(query, sel.filtro)
    return query.order_by(Cobranza.numero).all()


@router.post("/asignar", response_model=ResultadoMasivo)
def asignar(datos: Asignacion, db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_autorizado)):
    ejecutivos = []
    for eid in dict.fromkeys(datos.ejecutivo_ids):
        u = db.get(Usuario, eid)
        if u is None or not u.activo:
            raise HTTPException(status_code=404, detail="Uno de los ejecutivos no existe o está inactivo.")
        ejecutivos.append(u)
    nombres = {u.id: u.nombre for u in db.query(Usuario).all()}
    cobranzas = _elegidas(db, datos)
    abiertas = [c for c in cobranzas if c.estado in ABIERTAS]
    cambiadas = 0
    reparto: dict = {}
    for i, cob in enumerate(abiertas):
        nuevo = ejecutivos[i % len(ejecutivos)].id if ejecutivos else None
        if nuevo is not None:
            reparto[nombres[nuevo]] = reparto.get(nombres[nuevo], 0) + 1
        if cob.ejecutivo_id == nuevo:
            continue
        antes = nombres.get(cob.ejecutivo_id, "sin ejecutivo") if cob.ejecutivo_id else "sin ejecutivo"
        cob.ejecutivo_id = nuevo
        texto = (f"ASIGNADA A {nombres[nuevo]} (antes: {antes})." if nuevo
                 else f"SE QUITA LA ASIGNACIÓN (antes: {antes}).")
        registrar_cambio(db, [cob.id], usuario.id, "cambio_datos", texto)
        cambiadas += 1
    db.commit()
    return ResultadoMasivo(seleccionadas=len(cobranzas), cambiadas=cambiadas,
                           omitidas=len(cobranzas) - cambiadas, por_ejecutivo=reparto)


@router.post("/eliminar", response_model=ResultadoMasivo)
def eliminar_de_cartera(datos: Eliminacion, db: Session = Depends(get_db),
                        usuario: Usuario = Depends(usuario_autorizado)):
    cobranzas = _elegidas(db, datos)
    hoy = hoy_chile()
    cambiadas = 0
    for cob in cobranzas:
        if cob.estado not in ABIERTAS:
            continue
        cob.estado, cob.motivo_cierre, cob.fecha_cierre = "eliminada", "eliminada_cartera", hoy
        registrar_cambio(db, [cob.id], usuario.id, "eliminada_cartera",
                         f"ELIMINADA DE CARTERA por indicación del cliente. Motivo: {datos.motivo.strip()}")
        cambiadas += 1
    db.commit()
    return ResultadoMasivo(seleccionadas=len(cobranzas), cambiadas=cambiadas,
                           omitidas=len(cobranzas) - cambiadas)


class Ejecutivo(BaseModel):
    id: UUID
    nombre: str
    rol: Optional[str] = None
    abiertas: int          # cobranzas abiertas asignadas hoy


@router.get("/ejecutivos", response_model=List[Ejecutivo])
def ejecutivos(db: Session = Depends(get_db)):
    """A quién se puede asignar cartera, con cuántas cobranzas abiertas tiene cada uno."""
    carga = dict(db.query(Cobranza.ejecutivo_id, func.count(Cobranza.id))
                 .filter(Cobranza.estado.in_(ABIERTAS), Cobranza.ejecutivo_id.isnot(None))
                 .group_by(Cobranza.ejecutivo_id).all())
    return [Ejecutivo(id=u.id, nombre=u.nombre, rol=u.rol_nombre, abiertas=carga.get(u.id, 0))
            for u in db.query(Usuario).filter(Usuario.activo.is_(True)).order_by(Usuario.nombre)
            if u.rol_nombre not in ("mandante", "viewer")]

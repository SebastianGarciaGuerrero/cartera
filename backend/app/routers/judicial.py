"""
Módulo judicial (plan profesional o superior).

  GET  /api/judicial/resumen                 → números de la bandeja
  GET  /api/judicial/catalogos               → procedimientos, etapas, resultados, bienes, gastos
  GET  /api/judicial/para-demanda            → en preparación + sugeridas por la regla del cliente
  GET  /api/judicial/causas                  → bandeja (filtros: estado, etapa, plazo, cliente, q)
  POST /api/judicial/causas                  → presentar demanda (una o varias cobranzas)
  GET  /api/judicial/causas/{id}             → ficha de la causa
  PUT  /api/judicial/causas/{id}             → corregir datos (rol, tribunal, abogado…)
  POST /api/judicial/causas/{id}/cobranzas   → sumar otra cobranza del mismo deudor
  POST /api/judicial/causas/{id}/tramites    → registrar trámite (con gasto opcional)
  POST /api/judicial/causas/{id}/terminar    → cerrar la causa (y sus cobranzas)
  POST /api/judicial/causas/{id}/embargos    → registrar embargo
  PUT  /api/judicial/embargos/{id}           → actualizar embargo
  GET/POST /api/judicial/tribunales          → catálogo (sistema + propios)
  GET/POST /api/judicial/tipos-tramite, PUT /api/judicial/tipos-tramite/{id}

Los trámites no se editan ni se borran (como las gestiones): un error se
corrige con una observación.
"""

from datetime import date
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import ciclo, judicial
from app.database import get_db
from app.indicadores import hoy_chile
from app.models.cobranza import Cobranza
from app.models.judicial import Causa, CausaCobranza, Embargo, Gasto, TipoTramite, Tramite, Tribunal
from app.models.usuario import Usuario
from app.planes import requiere_funcion
from app.schemas.judicial import (
    AgregarCobranza, CausaCreate, CausaDetalle, CausaFila, CausaUpdate, EmbargoBase,
    EmbargoResponse, EmbargoUpdate, ParaDemanda, ResumenJudicial, TerminarCausa,
    TipoTramiteBase, TipoTramiteResponse, TipoTramiteUpdate, TramiteCreate, TramiteRegistrado,
    TribunalCreate, TribunalResponse,
)
from app.security import get_current_user, usuario_autorizado
from app.permisos import requiere_permiso

router = APIRouter(
    prefix="/api/judicial",
    tags=["Judicial"],
    dependencies=[Depends(usuario_autorizado), Depends(requiere_funcion("judicial"))],
)


def _causa(db: Session, causa_id: UUID) -> Causa:
    causa = db.get(Causa, causa_id)
    if causa is None:
        raise HTTPException(status_code=404, detail="Causa no encontrada")
    return causa


def _tribunal_nombre(db: Session, tribunal_id: Optional[int]) -> Optional[str]:
    if tribunal_id is None:
        return None
    tribunal = db.get(Tribunal, tribunal_id)
    if tribunal is None:
        raise HTTPException(status_code=404, detail="El tribunal indicado no existe")
    return tribunal.nombre


def _validar_usuarios(db: Session, *ids: Optional[UUID]) -> None:
    for uid in ids:
        if uid is not None and db.get(Usuario, uid) is None:
            raise HTTPException(status_code=404, detail="El abogado o procurador indicado no existe")


def _tipo_tramite(db: Session, tipo_id: Optional[int]) -> Optional[TipoTramite]:
    if tipo_id is None:
        return None
    tipo = db.get(TipoTramite, tipo_id)
    if tipo is None:
        raise HTTPException(status_code=404, detail="El tipo de trámite no existe")
    return tipo


def _commit(db: Session, mensaje: str) -> None:
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        detalle = mensaje
        if "uq_causas_rol" in str(e.orig):
            detalle = "Ya existe una causa con ese rol en ese tribunal."
        raise HTTPException(status_code=400, detail=detalle)


# ------------------------------------------------------------------ resumen

@router.get("/resumen", response_model=ResumenJudicial)
def resumen(db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_user)):
    return judicial.resumen_judicial(db, usuario.organizacion_id, hoy_chile())


@router.get("/catalogos")
def catalogos():
    return {
        "procedimientos": judicial.PROCEDIMIENTOS,
        "etapas": judicial.ETAPAS_PROCESALES,
        "resultados": {k: v[0] for k, v in judicial.RESULTADOS.items()},
        "motivos_cierre": ciclo.MOTIVOS_CIERRE,
        "tipos_bien": judicial.TIPOS_BIEN,
        "estados_embargo": judicial.ESTADOS_EMBARGO,
        "tipos_gasto": judicial.TIPOS_GASTO,
        "estados_gasto": judicial.ESTADOS_GASTO,
    }


@router.get("/equipo")
def equipo(db: Session = Depends(get_db)):
    """Personas que pueden llevar una causa (para elegir abogado y procurador)."""
    personas = db.query(Usuario).filter(Usuario.activo.is_(True)).order_by(Usuario.nombre).all()
    return [{"id": u.id, "nombre": u.nombre, "rol": u.rol_nombre} for u in personas
            if u.rol_nombre in ("admin", "supervisor", "operador", "abogado", "procurador")]


@router.get("/para-demanda", response_model=ParaDemanda)
def para_demanda(db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_user)):
    hoy = hoy_chile()
    org = usuario.organizacion_id
    return {
        "preparacion": ciclo.cobranzas_para_demanda(db, org, hoy, preparacion=True),
        "sugeridas": ciclo.cobranzas_para_demanda(db, org, hoy, preparacion=False, limite=200),
    }


# ------------------------------------------------------------------ causas

@router.get("/causas", response_model=List[CausaFila])
def listar_causas(
    response: Response,
    estado: Optional[str] = Query("vigente", pattern="^(vigente|terminada|todas)$"),
    etapa: Optional[str] = None,
    plazo: Optional[str] = Query(None, pattern="^(vencido|semana|abandono)$"),
    cliente_id: Optional[UUID] = None,
    responsable_id: Optional[UUID] = None,
    mias: bool = False,
    q: Optional[str] = Query(None, max_length=100),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    total, filas = judicial.listar_causas(
        db, usuario.organizacion_id, hoy_chile(),
        estado=None if estado == "todas" else estado, etapa=etapa, cliente_id=cliente_id,
        responsable_id=usuario.id if mias else responsable_id, q=q or None, plazo=plazo,
        limite=limit, desde=skip,
    )
    response.headers["X-Total-Count"] = str(total)
    return filas


@router.post("/causas", response_model=CausaDetalle, status_code=status.HTTP_201_CREATED, dependencies=[Depends(requiere_permiso("judicial_causas"))])
def presentar_demanda(datos: CausaCreate, db: Session = Depends(get_db),
                      usuario: Usuario = Depends(get_current_user)):
    campos = datos.model_dump(exclude={"cobranza_ids"})
    campos["fecha_ingreso"] = campos.get("fecha_ingreso") or hoy_chile()
    _validar_usuarios(db, campos.get("abogado_id"), campos.get("procurador_id"))
    tribunal = _tribunal_nombre(db, campos.get("tribunal_id"))
    try:
        causa = judicial.crear_causa(db, campos, datos.cobranza_ids, usuario.id, tribunal)
        db.flush()
    except IntegrityError as e:
        db.rollback()
        detalle = ("Ya existe una causa con ese rol en ese tribunal." if "uq_causas_rol" in str(e.orig)
                   else "No se pudo registrar la demanda.")
        raise HTTPException(status_code=400, detail=detalle)
    _commit(db, "No se pudo registrar la demanda.")
    return ficha_causa(causa.id, db)


@router.get("/causas/{causa_id}", response_model=CausaDetalle)
def ficha_causa(causa_id: UUID, db: Session = Depends(get_db)):
    causa = _causa(db, causa_id)
    hoy = hoy_chile()
    tramites = (db.query(Tramite).filter(Tramite.causa_id == causa.id)
                .order_by(Tramite.fecha.desc(), Tramite.created_at.desc()).all())
    ultimo = next((t for t in tramites if t.tipo_id is not None), None)
    ultima_fecha = ultimo.fecha if ultimo else causa.fecha_ingreso
    gastos = (db.query(Gasto).filter(Gasto.causa_id == causa.id)
              .order_by(Gasto.fecha.desc(), Gasto.created_at.desc()).all())
    embargos = db.query(Embargo).filter(Embargo.causa_id == causa.id).order_by(Embargo.created_at).all()
    cobranzas = sorted((v.cobranza for v in causa.vinculos), key=lambda c: c.numero)
    cliente = causa.cliente
    dias = (hoy - ultima_fecha).days
    return {
        "id": causa.id, "rol": causa.rol, "tribunal_id": causa.tribunal_id,
        "tribunal": causa.tribunal.nombre if causa.tribunal else None,
        "procedimiento": causa.procedimiento,
        "procedimiento_nombre": judicial.PROCEDIMIENTOS.get(causa.procedimiento, causa.procedimiento),
        "etapa_procesal": causa.etapa_procesal, "estado": causa.estado, "resultado": causa.resultado,
        "fecha_ingreso": causa.fecha_ingreso, "fecha_termino": causa.fecha_termino,
        "cuantia": causa.cuantia, "caratula": causa.caratula,
        "cliente_id": causa.cliente_id,
        "cliente": (cliente.nombre_fantasia or cliente.razon_social) if cliente else "",
        "deudor_id": causa.deudor_id, "deudor": causa.deudor.nombre if causa.deudor else "",
        "deudor_rut": causa.deudor.rut if causa.deudor else None,
        "abogado_id": causa.abogado_id, "abogado": causa.abogado.nombre if causa.abogado else None,
        "procurador_id": causa.procurador_id,
        "procurador": causa.procurador.nombre if causa.procurador else None,
        "observaciones": causa.observaciones,
        "cobranzas": cobranzas, "tramites": tramites, "embargos": embargos, "gastos": gastos,
        "plazo_fecha": ultimo.plazo_fecha if ultimo and causa.estado == "vigente" else None,
        "siguiente_id": ultimo.siguiente_id if ultimo else None,
        "siguiente_nombre": ultimo.siguiente_nombre if ultimo else None,
        "dias_sin_movimiento": dias,
        "riesgo_abandono": causa.estado == "vigente" and dias >= judicial.DIAS_AVISO_ABANDONO,
        "total_gastos": sum((Decimal(g.monto) for g in gastos if g.estado != "anulado"), Decimal(0)),
    }


@router.put("/causas/{causa_id}", response_model=CausaDetalle, dependencies=[Depends(requiere_permiso("judicial_causas"))])
def corregir_causa(causa_id: UUID, datos: CausaUpdate, db: Session = Depends(get_db)):
    causa = _causa(db, causa_id)
    cambios = datos.model_dump(exclude_unset=True)
    _validar_usuarios(db, cambios.get("abogado_id"), cambios.get("procurador_id"))
    if "tribunal_id" in cambios:
        _tribunal_nombre(db, cambios["tribunal_id"])
    for campo, valor in cambios.items():
        setattr(causa, campo, valor)
    _commit(db, "No se pudo actualizar la causa.")
    return ficha_causa(causa.id, db)


@router.post("/causas/{causa_id}/cobranzas", response_model=CausaDetalle, dependencies=[Depends(requiere_permiso("judicial_causas"))])
def agregar_cobranza(causa_id: UUID, datos: AgregarCobranza, db: Session = Depends(get_db),
                     usuario: Usuario = Depends(get_current_user)):
    causa = _causa(db, causa_id)
    if causa.estado != "vigente":
        raise HTTPException(status_code=400, detail="La causa está terminada.")
    if db.get(CausaCobranza, (causa.id, datos.cobranza_id)) is not None:
        raise HTTPException(status_code=400, detail="La cobranza ya está en esta causa.")
    (cob,) = judicial.validar_cobranzas_para_causa(db, [datos.cobranza_id], causa.cliente_id, causa.deudor_id)
    judicial.pasar_a_judicial(db, cob, causa, usuario.id, causa.tribunal.nombre if causa.tribunal else None)
    ciclo.fijar_contexto(db, usuario.id, "")
    judicial.registrar_tramite(db, causa, None, hoy_chile(),
                               f"Se agrega a la causa la cobranza N° {cob.numero}.", usuario.id)
    _commit(db, "No se pudo agregar la cobranza.")
    return ficha_causa(causa.id, db)


@router.post("/causas/{causa_id}/tramites", response_model=TramiteRegistrado,
             status_code=status.HTTP_201_CREATED, dependencies=[Depends(requiere_permiso("judicial_tramites"))])
def registrar_tramite(causa_id: UUID, datos: TramiteCreate, db: Session = Depends(get_db),
                      usuario: Usuario = Depends(get_current_user)):
    causa = _causa(db, causa_id)
    tipo = _tipo_tramite(db, datos.tipo_id)
    if datos.siguiente_id is not None:
        _tipo_tramite(db, datos.siguiente_id)
    fecha = datos.fecha or hoy_chile()
    if fecha > hoy_chile():
        raise HTTPException(status_code=422, detail="La fecha del trámite no puede ser futura.")
    plazo = datos.plazo_fecha
    if plazo is not None and plazo < fecha:
        raise HTTPException(status_code=422, detail="El plazo no puede ser anterior a la fecha del trámite.")
    tramite = judicial.registrar_tramite(
        db, causa, tipo, fecha, datos.descripcion, usuario.id, plazo_fecha=plazo,
        siguiente_id=datos.siguiente_id, gasto=datos.gasto.model_dump() if datos.gasto else None,
        sin_plazo=datos.sin_plazo,
    )
    _commit(db, "No se pudo registrar el trámite.")
    db.refresh(tramite)
    gasto = db.query(Gasto.id).filter(Gasto.tramite_id == tramite.id).first()
    return {
        "tramite": tramite,
        "etapa_procesal": causa.etapa_procesal,
        "propone_resultado": tipo.resultado if tipo else None,
        "gasto_id": gasto[0] if gasto else None,
    }


@router.post("/causas/{causa_id}/terminar", response_model=CausaDetalle, dependencies=[Depends(requiere_permiso("judicial_causas"))])
def terminar(causa_id: UUID, datos: TerminarCausa, db: Session = Depends(get_db),
             usuario: Usuario = Depends(get_current_user)):
    causa = _causa(db, causa_id)
    judicial.terminar_causa(db, causa, datos.resultado, datos.fecha or hoy_chile(), usuario.id,
                            datos.motivo_cierre, datos.nota)
    _commit(db, "No se pudo terminar la causa.")
    return ficha_causa(causa.id, db)


# ------------------------------------------------------------------ embargos

@router.post("/causas/{causa_id}/embargos", response_model=EmbargoResponse,
             status_code=status.HTTP_201_CREATED, dependencies=[Depends(requiere_permiso("judicial_tramites"))])
def registrar_embargo(causa_id: UUID, datos: EmbargoBase, db: Session = Depends(get_db),
                      usuario: Usuario = Depends(get_current_user)):
    causa = _causa(db, causa_id)
    embargo = Embargo(**datos.model_dump(), causa_id=causa.id, creado_por=usuario.id)
    db.add(embargo)
    _commit(db, "No se pudo registrar el embargo.")
    db.refresh(embargo)
    return embargo


@router.put("/embargos/{embargo_id}", response_model=EmbargoResponse, dependencies=[Depends(requiere_permiso("judicial_tramites"))])
def actualizar_embargo(embargo_id: UUID, datos: EmbargoUpdate, db: Session = Depends(get_db)):
    embargo = db.get(Embargo, embargo_id)
    if embargo is None:
        raise HTTPException(status_code=404, detail="Embargo no encontrado")
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        setattr(embargo, campo, valor)
    _commit(db, "No se pudo actualizar el embargo.")
    db.refresh(embargo)
    return embargo


# ------------------------------------------------------------------ catálogos

@router.get("/tribunales", response_model=List[TribunalResponse])
def tribunales(db: Session = Depends(get_db)):
    return (db.query(Tribunal).filter(Tribunal.activo.is_(True))
            .order_by(Tribunal.ciudad, Tribunal.nombre).all())


@router.post("/tribunales", response_model=TribunalResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(requiere_permiso("judicial_causas"))])
def crear_tribunal(datos: TribunalCreate, db: Session = Depends(get_db)):
    tribunal = Tribunal(**datos.model_dump())
    db.add(tribunal)
    _commit(db, "Ya existe un tribunal con ese nombre.")
    db.refresh(tribunal)
    return tribunal


@router.get("/tipos-tramite", response_model=List[TipoTramiteResponse])
def tipos_tramite(todos: bool = False, db: Session = Depends(get_db)):
    q = db.query(TipoTramite)
    if not todos:
        q = q.filter(TipoTramite.activo.is_(True))
    return q.order_by(TipoTramite.orden, TipoTramite.nombre).all()


@router.post("/tipos-tramite", response_model=TipoTramiteResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(requiere_permiso("judicial_causas"))])
def crear_tipo_tramite(datos: TipoTramiteBase, db: Session = Depends(get_db)):
    if datos.siguiente_id is not None:
        _tipo_tramite(db, datos.siguiente_id)
    tipo = TipoTramite(**datos.model_dump(), orden=1000)
    db.add(tipo)
    _commit(db, "No se pudo crear el trámite.")
    db.refresh(tipo)
    return tipo


@router.put("/tipos-tramite/{tipo_id}", response_model=TipoTramiteResponse, dependencies=[Depends(requiere_permiso("judicial_causas"))])
def editar_tipo_tramite(tipo_id: int, datos: TipoTramiteUpdate, db: Session = Depends(get_db)):
    tipo = _tipo_tramite(db, tipo_id)
    if not tipo.propio:
        raise HTTPException(status_code=403,
                            detail="Los trámites del sistema no se editan; cree uno propio con sus plazos.")
    cambios = datos.model_dump(exclude_unset=True)
    if cambios.get("siguiente_id") is not None:
        _tipo_tramite(db, cambios["siguiente_id"])
    for campo, valor in cambios.items():
        setattr(tipo, campo, valor)
    _commit(db, "No se pudo actualizar el trámite.")
    db.refresh(tipo)
    return tipo



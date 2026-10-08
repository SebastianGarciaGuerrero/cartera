"""
Portal de mandantes (plan profesional: función `portal_mandantes`).

El usuario con rol `mandante` pertenece a la organización del estudio pero
está atado a UN cliente (usuarios.cliente_id): todo lo que ve se filtra por
ese cliente acá, además del aislamiento por organización de siempre.

  GET  /api/portal/resumen                   → totales y recupero mensual
  GET  /api/portal/cobranzas?q=&estado=      → sus cobranzas
  GET  /api/portal/cobranzas/{id}            → ficha: gestiones (sin notas
                                               internas), acuerdo, pagos
  GET  /api/portal/acuerdos/pendientes       → acuerdos esperando su aprobación
  POST /api/portal/acuerdos/{id}/aprobar     → aprueba (queda en el historial)
  POST /api/portal/acuerdos/{id}/observar    → no aprueba y deja el motivo
  GET  /api/portal/acuerdos/{id}/documento   → Word del acuerdo
  GET  /api/portal/exportar/recupero|rendicion?anio=&mes= → Excel del mes
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.indicadores import hoy_chile
from app.models.acuerdo import AcuerdoPago
from app.models.cliente import Cliente
from app.models.cobranza import Cobranza
from app.models.deudor import Deudor
from app.models.gestion import Gestion, TipoGestion, tipo_de_sistema
from app.models.pago import Pago
from app.models.usuario import Usuario
from app.planes import requiere_funcion
from app.schemas.acuerdo import AcuerdoDetalle
from app.security import get_current_user

router = APIRouter(prefix="/api/portal", tags=["Portal de mandantes"])

# Tipos de gestión que son de uso interno del estudio y no se muestran.
TIPOS_INTERNOS = {"nota", "automatica"}


def usuario_mandante(
    usuario: Usuario = Depends(get_current_user),
    _plan=Depends(requiere_funcion("portal_mandantes")),
) -> Usuario:
    if usuario.rol_nombre != "mandante" or usuario.cliente_id is None:
        raise HTTPException(status_code=403, detail="Esta sección es para los usuarios del portal de clientes.")
    return usuario


def _cobranza_propia(db: Session, usuario: Usuario, cobranza_id: UUID) -> Cobranza:
    cob = db.get(Cobranza, cobranza_id)
    if cob is None or cob.cliente_id != usuario.cliente_id:
        raise HTTPException(status_code=404, detail="Cobranza no encontrada")
    return cob


def _acuerdo_propio(db: Session, usuario: Usuario, acuerdo_id: UUID) -> AcuerdoPago:
    acuerdo = db.get(AcuerdoPago, acuerdo_id)
    if acuerdo is None or acuerdo.cobranza.cliente_id != usuario.cliente_id:
        raise HTTPException(status_code=404, detail="Acuerdo no encontrado")
    return acuerdo


# ------------------------------------------------------------ resumen

class MesPortal(BaseModel):
    mes: date
    capital: Decimal


class ResumenPortal(BaseModel):
    cliente: str
    estudio: str
    asignado: Decimal
    saldo_abierto: Decimal
    casos_abiertos: int
    casos_totales: int
    recuperado_total: Decimal
    recuperado_mes: Decimal
    acuerdos_vigentes: int
    acuerdos_por_aprobar: int
    meses: List[MesPortal]


@router.get("/resumen", response_model=ResumenPortal)
def resumen(request: Request, db: Session = Depends(get_db),
            usuario: Usuario = Depends(usuario_mandante)):
    cli = db.get(Cliente, usuario.cliente_id)
    cobs = db.query(Cobranza).filter(Cobranza.cliente_id == usuario.cliente_id)
    abiertas = cobs.filter(Cobranza.estado.in_(("activa", "acuerdo_pago", "judicial")))
    hoy = hoy_chile()
    inicio_mes = hoy.replace(day=1)
    pagos = (db.query(Pago).join(Cobranza, Cobranza.id == Pago.cobranza_id)
             .filter(Cobranza.cliente_id == usuario.cliente_id))
    capital_total = pagos.with_entities(func.coalesce(func.sum(Pago.capital), 0)).scalar()
    capital_mes = (pagos.filter(Pago.fecha_pago >= inicio_mes)
                   .with_entities(func.coalesce(func.sum(Pago.capital), 0)).scalar())
    acuerdos = (db.query(AcuerdoPago).join(Cobranza, Cobranza.id == AcuerdoPago.cobranza_id)
                .filter(Cobranza.cliente_id == usuario.cliente_id, AcuerdoPago.estado == "vigente"))

    # Recupero de capital de los últimos 12 meses.
    total_meses = hoy.year * 12 + hoy.month - 1
    meses = []
    for i in range(11, -1, -1):
        t = total_meses - i
        desde = date(t // 12, t % 12 + 1, 1)
        hasta = date((t + 1) // 12, (t + 1) % 12 + 1, 1) - timedelta(days=1)
        capital = (pagos.filter(Pago.fecha_pago >= desde, Pago.fecha_pago <= hasta)
                   .with_entities(func.coalesce(func.sum(Pago.capital), 0)).scalar())
        meses.append(MesPortal(mes=desde, capital=capital))

    return ResumenPortal(
        cliente=(cli.nombre_fantasia or cli.razon_social) if cli else "",
        estudio=request.state.organizacion.nombre,
        asignado=cobs.with_entities(func.coalesce(func.sum(Cobranza.monto_original), 0)).scalar(),
        saldo_abierto=abiertas.with_entities(func.coalesce(func.sum(Cobranza.monto_actual), 0)).scalar(),
        casos_abiertos=abiertas.count(),
        casos_totales=cobs.count(),
        recuperado_total=capital_total,
        recuperado_mes=capital_mes,
        acuerdos_vigentes=acuerdos.count(),
        acuerdos_por_aprobar=acuerdos.filter(AcuerdoPago.firma_cliente != "firmado_confirmado").count(),
        meses=meses,
    )


# ------------------------------------------------------------ cobranzas

class CobranzaPortal(BaseModel):
    id: UUID
    numero: int
    id_externo: Optional[str]
    deudor: str
    rut: str
    monto_original: Decimal
    monto_actual: Decimal
    estado: str
    fecha_ingreso: Optional[date]
    ultima_gestion: Optional[date] = None


@router.get("/cobranzas", response_model=List[CobranzaPortal])
def mis_cobranzas(
    response: Response,
    q: Optional[str] = Query(None, max_length=100),
    estado: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_mandante),
):
    query = (db.query(Cobranza, Deudor).join(Deudor, Deudor.id == Cobranza.deudor_id)
             .filter(Cobranza.cliente_id == usuario.cliente_id))
    if estado:
        query = query.filter(Cobranza.estado == estado)
    if q:
        patron = f"%{q.strip()}%"
        query = query.filter(or_(Deudor.nombre.ilike(patron), Deudor.rut.ilike(patron.replace(".", "")),
                                 Cobranza.id_externo.ilike(patron)))
    response.headers["X-Total-Count"] = str(query.count())
    filas = query.order_by(Cobranza.numero.desc()).offset(skip).limit(limit).all()
    ultimas = dict(
        db.query(Gestion.cobranza_id, func.max(Gestion.fecha_gestion))
        .filter(Gestion.cobranza_id.in_([c.id for c, _ in filas])).group_by(Gestion.cobranza_id).all()
    ) if filas else {}
    return [
        CobranzaPortal(
            id=c.id, numero=c.numero, id_externo=c.id_externo, deudor=d.nombre, rut=d.rut,
            monto_original=c.monto_original, monto_actual=c.monto_actual, estado=c.estado,
            fecha_ingreso=c.fecha_ingreso,
            ultima_gestion=ultimas[c.id].date() if c.id in ultimas else None,
        )
        for c, d in filas
    ]


class GestionPortal(BaseModel):
    fecha: date
    tipo: Optional[str]
    descripcion: str


class PagoPortal(BaseModel):
    fecha_pago: date
    monto: Decimal
    capital: Decimal
    forma_pago: Optional[str]


class FichaPortal(CobranzaPortal):
    gestiones: List[GestionPortal]
    pagos: List[PagoPortal]
    acuerdo: Optional[AcuerdoDetalle] = None


@router.get("/cobranzas/{cobranza_id}", response_model=FichaPortal)
def ficha(cobranza_id: UUID, db: Session = Depends(get_db),
          usuario: Usuario = Depends(usuario_mandante)):
    cob = _cobranza_propia(db, usuario, cobranza_id)
    tipos = {t.id: t for t in db.query(TipoGestion).all()}
    gestiones = [
        GestionPortal(fecha=g.fecha_gestion.date(), tipo=tipos[g.tipo_id].nombre if g.tipo_id in tipos else None,
                      descripcion=g.descripcion)
        for g in sorted(cob.gestiones, key=lambda g: g.fecha_gestion, reverse=True)
        if not (g.tipo_id in tipos and tipos[g.tipo_id].codigo in TIPOS_INTERNOS)
    ]
    acuerdo = next((a for a in sorted(cob.acuerdos, key=lambda a: a.created_at or 0, reverse=True)), None)
    return FichaPortal(
        id=cob.id, numero=cob.numero, id_externo=cob.id_externo, deudor=cob.deudor.nombre,
        rut=cob.deudor.rut, monto_original=cob.monto_original, monto_actual=cob.monto_actual,
        estado=cob.estado, fecha_ingreso=cob.fecha_ingreso,
        ultima_gestion=gestiones[0].fecha if gestiones else None,
        gestiones=gestiones,
        pagos=[PagoPortal(fecha_pago=p.fecha_pago, monto=p.monto, capital=p.capital or 0,
                          forma_pago=p.forma_pago) for p in cob.pagos],
        acuerdo=acuerdo,
    )


# ------------------------------------------------------------ acuerdos

class AcuerdoPendiente(BaseModel):
    id: UUID
    cobranza_id: UUID
    numero_cobranza: int
    deudor: str
    fecha_acuerdo: date
    pie: Decimal
    monto_total_acordado: Decimal
    numero_cuotas: int
    firma_cliente: str
    observaciones: Optional[str]


class Observacion(BaseModel):
    motivo: str = Field(..., min_length=3, max_length=1000)


@router.get("/acuerdos/pendientes", response_model=List[AcuerdoPendiente])
def acuerdos_pendientes(db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_mandante)):
    filas = (db.query(AcuerdoPago).join(Cobranza, Cobranza.id == AcuerdoPago.cobranza_id)
             .filter(Cobranza.cliente_id == usuario.cliente_id, AcuerdoPago.estado == "vigente",
                     AcuerdoPago.firma_cliente != "firmado_confirmado")
             .order_by(AcuerdoPago.fecha_acuerdo).all())
    return [AcuerdoPendiente(
        id=a.id, cobranza_id=a.cobranza_id, numero_cobranza=a.cobranza.numero,
        deudor=a.cobranza.deudor.nombre, fecha_acuerdo=a.fecha_acuerdo, pie=a.pie or 0,
        monto_total_acordado=a.monto_total_acordado, numero_cuotas=a.numero_cuotas,
        firma_cliente=a.firma_cliente, observaciones=a.observaciones,
    ) for a in filas]


def _gestion_portal(db: Session, cobranza_id, usuario: Usuario, texto: str) -> None:
    tipo = tipo_de_sistema(db, "acuerdo")
    db.add(Gestion(cobranza_id=cobranza_id, usuario_id=usuario.id,
                   tipo_id=tipo.id if tipo else None, descripcion=texto))


@router.post("/acuerdos/{acuerdo_id}/aprobar", status_code=204)
def aprobar(acuerdo_id: UUID, db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_mandante)):
    acuerdo = _acuerdo_propio(db, usuario, acuerdo_id)
    if acuerdo.estado != "vigente":
        raise HTTPException(status_code=400, detail="Solo se aprueban acuerdos vigentes.")
    acuerdo.firma_cliente = "firmado_confirmado"
    acuerdo.fecha_firma = hoy_chile()
    _gestion_portal(db, acuerdo.cobranza_id, usuario,
                    f"Acuerdo APROBADO por el mandante ({usuario.nombre}) desde el portal.")
    db.commit()
    return Response(status_code=204)


@router.post("/acuerdos/{acuerdo_id}/observar", status_code=204)
def observar(acuerdo_id: UUID, datos: Observacion, db: Session = Depends(get_db),
             usuario: Usuario = Depends(usuario_mandante)):
    acuerdo = _acuerdo_propio(db, usuario, acuerdo_id)
    acuerdo.firma_cliente = "pendiente"
    _gestion_portal(db, acuerdo.cobranza_id, usuario,
                    f"El mandante ({usuario.nombre}) NO aprueba el acuerdo: {datos.motivo}")
    db.commit()
    return Response(status_code=204)


@router.get("/acuerdos/{acuerdo_id}/documento")
def documento(acuerdo_id: UUID, request: Request, db: Session = Depends(get_db),
              usuario: Usuario = Depends(usuario_mandante)):
    from app.routers.documentos import documento_acuerdo
    _acuerdo_propio(db, usuario, acuerdo_id)
    return documento_acuerdo(acuerdo_id, request, db)


# ------------------------------------------------------------ Excel

@router.get("/exportar/{informe}")
def exportar(informe: str, anio: Optional[int] = Query(None, ge=2000, le=2100),
             mes: Optional[int] = Query(None, ge=1, le=12), db: Session = Depends(get_db),
             usuario: Usuario = Depends(usuario_mandante)):
    from app.routers import exportar as exp
    if informe == "recupero":
        return exp.exportar_recupero(anio=anio, mes=mes, cliente_id=usuario.cliente_id, db=db, usuario=usuario)
    if informe == "rendicion":
        return exp.exportar_rendicion(anio=anio, mes=mes, cliente_id=usuario.cliente_id, db=db, usuario=usuario)
    raise HTTPException(status_code=404, detail="Informe no disponible")

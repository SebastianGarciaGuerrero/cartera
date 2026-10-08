"""
Portal del deudor (plan profesional: función `portal_deudor`).

El deudor no tiene cuenta: el estudio genera un enlace personal desde la
ficha y se lo manda. Para abrirlo el deudor escribe su RUT: si el enlace
llega a otra persona no ve nada (la ley prohíbe informar la deuda a
terceros). Ve solo lo suyo y lo que le sirve para ponerse al día: estado de
sus deudas, avance del convenio, cuotas atrasadas, pagos y cómo pagar.
Nunca gestiones, notas, honorarios ni nombres del equipo.

Para el equipo (con sesión):
  GET    /api/deudores/{id}/enlace  → enlace vigente (sin el token) o null
  POST   /api/deudores/{id}/enlace  → genera uno nuevo (revoca el anterior)
  DELETE /api/deudores/{id}/enlace  → lo desactiva

Público (sin sesión):
  POST /api/publico/estado  {token, rut} → estado del deudor

El token va en el fragmento de la URL (/estado#t=...), que el navegador no
envía al servidor: no queda en logs ni en el Referer.
"""

import base64
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Literal, Optional
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auditoria import CLAVE_CONTEXTO
from app.config import settings
from app.database import get_db
from app.indicadores import ZONA_CHILE, hoy_chile
from app.models.cobranza import Cobranza
from app.models.deudor import Deudor
from app.models.empresa import Empresa
from app.models.enlace_deudor import EnlaceDeudor
from app.models.gestion import Gestion, tipo_de_sistema
from app.models.organizacion import Organizacion
from app.models.usuario import Usuario
from app.planes import funciones_de, requiere_funcion
from app.routers.mensajes import telefono_whatsapp
from app.rut import normalizar_rut
from app.security import ip_cliente, usuario_autorizado
from app.sesiones import controlar_limite_ip, hash_token, nuevo_token, registrar_evento
from app.tenancy import activar_organizacion, sesion_sistema

DURACION_ENLACE = timedelta(days=90)
MAX_INTENTOS_RUT = 5
# 'archivada' y 'castigo' son clasificaciones internas del estudio: no se muestran.
ESTADOS_VISIBLES = ("activa", "acuerdo_pago", "judicial", "pagada")
ESTADOS_ABIERTOS = ("activa", "acuerdo_pago", "judicial")

NO_VALIDO = "Este enlace no es válido o ya venció. Solicite uno nuevo a quien se lo envió."
BLOQUEADO = "Por seguridad este enlace se bloqueó. Solicite uno nuevo a quien se lo envió."

equipo = APIRouter(
    prefix="/api/deudores",
    tags=["Portal del deudor"],
    dependencies=[Depends(usuario_autorizado), Depends(requiere_funcion("portal_deudor"))],
)
publico = APIRouter(prefix="/api/publico", tags=["Portal del deudor"])


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------ equipo

class EnlaceVigente(BaseModel):
    created_at: datetime
    expira_at: datetime
    creado_por: Optional[str] = None
    accesos: int
    ultimo_acceso_at: Optional[datetime] = None
    bloqueado: bool


class EnlaceNuevo(EnlaceVigente):
    url: str
    mensaje: str
    whatsapp_url: str
    mailto_url: Optional[str] = None


def _deudor(db: Session, deudor_id: UUID) -> Deudor:
    deudor = db.get(Deudor, deudor_id)
    if deudor is None:
        raise HTTPException(status_code=404, detail="Deudor no encontrado")
    return deudor


def _vigentes(db: Session, deudor_id: UUID):
    return db.query(EnlaceDeudor).filter(EnlaceDeudor.deudor_id == deudor_id,
                                         EnlaceDeudor.revocado_at.is_(None))


def _vista(db: Session, enlace: EnlaceDeudor) -> dict:
    creador = db.get(Usuario, enlace.creado_por)
    return dict(created_at=enlace.created_at, expira_at=enlace.expira_at,
                creado_por=creador.nombre if creador else None, accesos=enlace.accesos,
                ultimo_acceso_at=enlace.ultimo_acceso_at, bloqueado=enlace.bloqueado_at is not None)


@equipo.get("/{deudor_id}/enlace", response_model=Optional[EnlaceVigente])
def ver_enlace(deudor_id: UUID, db: Session = Depends(get_db)):
    _deudor(db, deudor_id)
    enlace = (_vigentes(db, deudor_id).filter(EnlaceDeudor.expira_at > _ahora())
              .order_by(EnlaceDeudor.created_at.desc()).first())
    return EnlaceVigente(**_vista(db, enlace)) if enlace else None


@equipo.post("/{deudor_id}/enlace", response_model=EnlaceNuevo, status_code=201)
def generar_enlace(deudor_id: UUID, request: Request, db: Session = Depends(get_db),
                   usuario: Usuario = Depends(usuario_autorizado)):
    deudor = _deudor(db, deudor_id)
    ahora = _ahora()
    for anterior in _vigentes(db, deudor_id):
        anterior.revocado_at = ahora
    token = nuevo_token()
    enlace = EnlaceDeudor(deudor_id=deudor.id, token_hash=hash_token(token), creado_por=usuario.id,
                          expira_at=ahora + DURACION_ENLACE)
    db.add(enlace)
    db.commit()
    db.refresh(enlace)

    url = f"{settings.url_publica.rstrip('/')}/estado#t={token}"
    emp = db.query(Empresa).first()
    empresa = (emp.nombre_fantasia or emp.razon_social) if emp else request.state.organizacion.nombre
    nombre = deudor.nombre.split()[0].capitalize() if deudor.nombre else ""
    mensaje = (
        f"Hola {nombre}, le escribimos de {empresa}. En este enlace puede revisar el estado "
        f"de su deuda y de su convenio de pago:\n\n{url}\n\n"
        "Para abrirlo se le pedirá su RUT. El enlace es personal: no lo comparta."
    )
    activos = [c for c in deudor.contactos if c.activo]
    telefono = next((c.valor for t in ("whatsapp", "celular", "telefono") for c in activos if c.tipo == t), None)
    email = next((c.valor for c in activos if c.tipo == "email"), None)
    numero_wa = telefono_whatsapp(telefono) if telefono else None
    return EnlaceNuevo(
        **_vista(db, enlace), url=url, mensaje=mensaje,
        whatsapp_url=f"https://wa.me/{numero_wa or ''}?text={quote(mensaje)}",
        mailto_url=(f"mailto:{quote(email)}?subject={quote('Estado de su deuda - ' + empresa)}"
                    f"&body={quote(mensaje)}") if email else None,
    )


@equipo.delete("/{deudor_id}/enlace", status_code=204)
def desactivar_enlace(deudor_id: UUID, db: Session = Depends(get_db)):
    _deudor(db, deudor_id)
    ahora = _ahora()
    for enlace in _vigentes(db, deudor_id):
        enlace.revocado_at = ahora
    db.commit()
    return Response(status_code=204)


# ------------------------------------------------------------ público

class AccesoEstado(BaseModel):
    token: str = Field(..., min_length=20, max_length=100)
    rut: str = Field(..., max_length=20)


class CuotaDeudor(BaseModel):
    numero: int
    vence: date
    monto: Decimal
    pagado: Decimal
    estado: Literal["pagada", "pendiente", "parcial", "atrasada"]


class ConvenioDeudor(BaseModel):
    estado: Literal["vigente", "cumplido"]
    fecha: Optional[date]
    total: Decimal
    pie: Decimal
    numero_cuotas: int
    cuotas_pagadas: int
    pagado: Decimal
    por_pagar: Decimal
    cuotas_atrasadas: int
    monto_atrasado: Decimal
    proxima: Optional[CuotaDeudor] = None
    cuotas: List[CuotaDeudor]


class PagoDeudor(BaseModel):
    fecha: date
    monto: Decimal


class DeudaDeudor(BaseModel):
    numero: int
    acreedor: str
    estado: str
    capital_pendiente: Decimal
    convenio: Optional[ConvenioDeudor] = None
    pagos: List[PagoDeudor]
    como_pagar: Optional[str] = None


class EstudioPublico(BaseModel):
    nombre: str
    telefonos: Optional[str] = None
    emails: Optional[str] = None
    horario: Optional[str] = None
    sitio_web: Optional[str] = None
    direccion: Optional[str] = None
    logo: Optional[str] = None  # data: URI (la página es pública, no puede pedir /api/empresa/logo)


class EstadoDeudor(BaseModel):
    nombre: str
    estudio: EstudioPublico
    deudas: List[DeudaDeudor]
    al: date
    enlace_vence: date


def _cuota(c, hoy: date) -> CuotaDeudor:
    if c.estado == "pagada":
        estado = "pagada"
    elif c.fecha_vencimiento < hoy:
        estado = "atrasada"
    elif c.estado == "pagada_parcial":
        estado = "parcial"
    else:
        estado = "pendiente"
    return CuotaDeudor(numero=c.numero_cuota, vence=c.fecha_vencimiento, monto=c.monto,
                       pagado=c.monto_pagado or 0, estado=estado)


def _convenio(cob: Cobranza, hoy: date) -> Optional[ConvenioDeudor]:
    acuerdo = next((a for a in cob.acuerdos if a.estado == "vigente"), None)
    if acuerdo is None:
        cumplidos = [a for a in cob.acuerdos if a.estado == "cumplido"]
        acuerdo = max(cumplidos, key=lambda a: a.fecha_acuerdo or date.min, default=None)
    if acuerdo is None:
        return None
    cuotas = [_cuota(c, hoy) for c in sorted(acuerdo.cuotas, key=lambda c: c.numero_cuota)]
    impagas = [c for c in cuotas if c.estado != "pagada"]
    atrasadas = [c for c in impagas if c.estado == "atrasada"]
    return ConvenioDeudor(
        estado=acuerdo.estado, fecha=acuerdo.fecha_acuerdo, total=acuerdo.monto_total_acordado,
        pie=acuerdo.pie or 0, numero_cuotas=acuerdo.numero_cuotas,
        cuotas_pagadas=len(cuotas) - len(impagas),
        pagado=sum((c.pagado for c in cuotas), Decimal(0)),
        por_pagar=sum((c.monto - c.pagado for c in impagas), Decimal(0)),
        cuotas_atrasadas=len(atrasadas),
        monto_atrasado=sum((c.monto - c.pagado for c in atrasadas), Decimal(0)),
        proxima=next((c for c in impagas if c.estado != "atrasada"), None),
        cuotas=cuotas,
    )


def _logo(emp: Optional[Empresa]) -> Optional[str]:
    if emp is None or not emp.tiene_logo or not emp.logo:
        return None
    return f"data:{emp.logo_tipo};base64,{base64.b64encode(emp.logo).decode()}"


@publico.post("/estado", response_model=EstadoDeudor)
def ver_estado(datos: AccesoEstado, request: Request, db: Session = Depends(get_db)):
    controlar_limite_ip(request, "estado_deudor")
    try:
        rut = normalizar_rut(datos.rut)
    except ValueError:
        raise HTTPException(status_code=422, detail="Revise el RUT: no es válido.")

    # 1) El enlace se busca en modo sistema: todavía no se sabe la organización.
    ahora = _ahora()
    with sesion_sistema() as sis:
        enlace = (sis.query(EnlaceDeudor).filter(EnlaceDeudor.token_hash == hash_token(datos.token))
                  .with_for_update().first())
        if enlace is None or enlace.revocado_at is not None or enlace.expira_at <= ahora:
            raise HTTPException(status_code=404, detail=NO_VALIDO)
        if enlace.bloqueado_at is not None:
            raise HTTPException(status_code=423, detail=BLOQUEADO)
        org = sis.get(Organizacion, enlace.organizacion_id)
        if org is None or not org.habilitada or "portal_deudor" not in funciones_de(org):
            raise HTTPException(status_code=404, detail=NO_VALIDO)

        deudor = sis.get(Deudor, enlace.deudor_id)
        if deudor is None or deudor.rut != rut:
            enlace.intentos_fallidos += 1
            if enlace.intentos_fallidos >= MAX_INTENTOS_RUT:
                enlace.bloqueado_at = ahora
            registrar_evento(sis, "portal_deudor_rut", False, request=request,
                             organizacion_id=enlace.organizacion_id, detalle={"enlace_id": str(enlace.id)})
            sis.commit()
            if enlace.bloqueado_at is not None:
                raise HTTPException(status_code=423, detail=BLOQUEADO)
            raise HTTPException(status_code=400, detail="El RUT no coincide con el de este enlace.")

        primera_del_dia = (enlace.ultimo_acceso_at is None
                           or enlace.ultimo_acceso_at.astimezone(ZONA_CHILE).date() < hoy_chile())
        enlace.intentos_fallidos = 0
        enlace.accesos += 1
        enlace.ultimo_acceso_at = ahora
        registrar_evento(sis, "portal_deudor", True, request=request,
                         organizacion_id=enlace.organizacion_id, detalle={"enlace_id": str(enlace.id)})
        sis.commit()
        org_id, deudor_id = enlace.organizacion_id, enlace.deudor_id
        creador, vence = enlace.creado_por, enlace.expira_at

    # 2) El resto, dentro de la organización del enlace (ORM + RLS).
    activar_organizacion(db, org_id)
    db.info[CLAVE_CONTEXTO] = {"usuario_id": None, "ip": ip_cliente(request)}
    deudor = db.get(Deudor, deudor_id)
    cobranzas = (db.query(Cobranza)
                 .filter(Cobranza.deudor_id == deudor_id, Cobranza.estado.in_(ESTADOS_VISIBLES))
                 .order_by(Cobranza.numero).all())

    # El ejecutivo ve en el historial que el deudor revisó su estado (una vez al día).
    if primera_del_dia:
        tipo = tipo_de_sistema(db, "automatica")
        for cob in cobranzas:
            if cob.estado in ESTADOS_ABIERTOS:
                db.add(Gestion(cobranza_id=cob.id, usuario_id=creador, tipo_id=tipo.id if tipo else None,
                               descripcion="El deudor abrió su estado de cuenta en línea (portal del deudor)."))
        db.commit()

    emp = db.query(Empresa).first()
    hoy = hoy_chile()
    deudas = []
    for cob in cobranzas:
        cliente = cob.cliente
        deudas.append(DeudaDeudor(
            numero=cob.numero,
            acreedor=(cliente.nombre_fantasia or cliente.razon_social) if cliente else "",
            estado=cob.estado,
            capital_pendiente=cob.monto_actual,
            convenio=_convenio(cob, hoy),
            pagos=[PagoDeudor(fecha=p.fecha_pago, monto=p.monto)
                   for p in sorted(cob.pagos, key=lambda p: p.fecha_pago, reverse=True)],
            como_pagar=((cliente.instrucciones_pago if cliente else None)
                        or (emp.instrucciones_pago if emp else None) or None),
        ))
    return EstadoDeudor(
        nombre=deudor.nombre,
        estudio=EstudioPublico(
            nombre=(emp.nombre_fantasia or emp.razon_social) if emp else "",
            telefonos=emp.telefonos if emp else None, emails=emp.emails if emp else None,
            horario=emp.horario_atencion if emp else None, sitio_web=emp.sitio_web if emp else None,
            direccion=", ".join(x for x in (emp.direccion, emp.ciudad) if x) if emp else None,
            logo=_logo(emp),
        ),
        deudas=deudas,
        al=hoy,
        enlace_vence=vence.astimezone(ZONA_CHILE).date(),
    )

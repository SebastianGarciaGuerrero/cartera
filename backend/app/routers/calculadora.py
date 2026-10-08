"""
Calculadora de cobranza (plan premium: función `calculadora_369`).

  GET  /api/indicadores/uf?fecha=       → UF del día (o de una fecha)
  POST /api/calculadora/honorarios      → honorarios 3-6-9 o judiciales de un capital
  POST /api/calculadora/abono           → separa un abono en capital + honorarios
  POST /api/calculadora/acuerdo         → plan de cuotas (simulación, no guarda)
  POST /api/calculadora/acuerdo/crear   → crea el acuerdo en la cobranza con
                                          ese plan: cuotas con su desglose,
                                          texto legal y gestión automática

Los porcentajes (judicial, comisión de pago en línea) salen de la
configuración de la organización; los tramos 3-6-9 son los de la ley.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import calculos
from app.database import get_db
from app.indicadores import hoy_chile, obtener_uf
from app.models.acuerdo import AcuerdoPago, Cuota
from app.models.cobranza import Cobranza
from app.models.gestion import Gestion, tipo_de_sistema
from app.models.usuario import Usuario
from app.planes import requiere_funcion
from app.operaciones import validar_sin_acuerdo_vigente
from app.schemas.acuerdo import AcuerdoDetalle
from app.security import get_current_user, usuario_autorizado

router = APIRouter(tags=["Calculadora"], dependencies=[Depends(usuario_autorizado)])
solo_premium = [Depends(requiere_funcion("calculadora_369"))]


def parametros_cobro(request: Request) -> dict:
    conf = (request.state.organizacion.configuracion or {}).get("cobro") or {}
    return {
        "pct_judicial": Decimal(str(conf.get("pct_judicial", calculos.PCT_JUDICIAL_DEFECTO))),
        "comision_pct": Decimal(str(conf.get("comision_pct", calculos.COMISION_FLOW_DEFECTO))),
    }


# ------------------------------------------------------------ UF

class UFRespuesta(BaseModel):
    fecha: date
    valor: Decimal
    fuente: Optional[str] = None


@router.get("/api/indicadores/uf", response_model=UFRespuesta)
def uf_del_dia(fecha: Optional[date] = Query(None, description="AAAA-MM-DD; por defecto hoy")):
    # El Banco Central publica la UF hasta el día 9 del mes siguiente.
    if fecha and fecha > hoy_chile() + timedelta(days=40):
        raise HTTPException(status_code=422, detail="La UF de fechas futuras aún no está publicada.")
    indicador = obtener_uf(fecha)
    if indicador is None:
        raise HTTPException(
            status_code=503,
            detail="No se pudo obtener la UF en este momento. Ingrésala a mano.",
        )
    return UFRespuesta(fecha=indicador.fecha, valor=indicador.valor, fuente=indicador.fuente)


# ------------------------------------------------------------ honorarios / abono

class TramoVista(BaseModel):
    desde_uf: Decimal
    hasta_uf: Optional[Decimal]
    porcentaje: Decimal
    monto_base: Decimal
    honorarios: Decimal


class HonorariosVista(BaseModel):
    modalidad: str
    capital: Decimal
    uf: Optional[Decimal]
    capital_uf: Optional[Decimal]
    tramos: List[TramoVista]
    total_honorarios: Decimal
    total_deuda: Decimal


def _vista_honorarios(h: calculos.Honorarios) -> HonorariosVista:
    r = calculos.redondear
    return HonorariosVista(
        modalidad=h.modalidad,
        capital=r(h.capital),
        uf=h.uf,
        capital_uf=h.capital_uf.quantize(Decimal("0.0001")) if h.capital_uf is not None else None,
        tramos=[TramoVista(desde_uf=t.desde_uf, hasta_uf=t.hasta_uf, porcentaje=t.porcentaje,
                           monto_base=r(t.monto_base), honorarios=r(t.honorarios))
                for t in h.tramos if t.monto_base > 0 or h.modalidad == "judicial"],
        total_honorarios=r(h.total_honorarios),
        total_deuda=r(h.total_deuda),
    )


class HonorariosEntrada(BaseModel):
    capital: Decimal = Field(..., gt=0, max_digits=15, decimal_places=2)
    uf: Optional[Decimal] = Field(None, gt=0)
    modalidad: Literal["extrajudicial", "judicial"] = "extrajudicial"


class AbonoEntrada(BaseModel):
    abono: Decimal = Field(..., gt=0, max_digits=15, decimal_places=2)
    uf: Optional[Decimal] = Field(None, gt=0)
    modalidad: Literal["extrajudicial", "judicial"] = "extrajudicial"


@router.post("/api/calculadora/honorarios", response_model=HonorariosVista, dependencies=solo_premium)
def calcular_honorarios(datos: HonorariosEntrada, request: Request):
    try:
        h = calculos.honorarios(datos.capital, datos.uf, datos.modalidad,
                                parametros_cobro(request)["pct_judicial"])
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _vista_honorarios(h)


@router.post("/api/calculadora/abono", response_model=HonorariosVista, dependencies=solo_premium)
def desglosar_abono(datos: AbonoEntrada, request: Request):
    """Lo que pagó el deudor → cuánto es capital (para el mandante) y cuánto honorarios."""
    try:
        h = calculos.capital_desde_abono(datos.abono, datos.uf, datos.modalidad,
                                         parametros_cobro(request)["pct_judicial"])
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    vista = _vista_honorarios(h)
    # Que capital + honorarios sumen exactamente el abono.
    vista.capital = calculos.redondear(h.capital)
    vista.total_honorarios = calculos.redondear(datos.abono) - vista.capital
    vista.total_deuda = calculos.redondear(datos.abono)
    return vista


# ------------------------------------------------------------ acuerdo

class AcuerdoEntrada(BaseModel):
    capital: Decimal = Field(..., gt=0, max_digits=15, decimal_places=2)
    numero_cuotas: int = Field(..., ge=1, le=120)
    tasa_mensual: Decimal = Field(Decimal(0), ge=0, le=10)
    uf: Optional[Decimal] = Field(None, gt=0)
    modalidad: Literal["extrajudicial", "judicial"] = "extrajudicial"
    abono_inicial: Decimal = Field(Decimal(0), ge=0)
    gastos_judiciales: Decimal = Field(Decimal(0), ge=0)
    con_comision: bool = False
    redondeo: Optional[Literal["arriba", "abajo"]] = None
    fecha_primera_cuota: Optional[date] = None
    dia_siguientes: Optional[int] = Field(None, ge=1, le=31)
    fecha_pie: Optional[date] = None


class FilaVista(BaseModel):
    numero: int
    fecha: Optional[date]
    capital: Decimal
    intereses: Decimal
    honorarios: Decimal
    gastos_judiciales: Decimal
    comision: Decimal
    total: Decimal


class PlanVista(BaseModel):
    modalidad: str
    capital: Decimal
    abono_inicial: Decimal
    capital_pie: Decimal
    honorarios_pie: Decimal
    capital_en_cuotas: Decimal
    numero_cuotas: int
    tasa_mensual: Decimal
    uf: Optional[Decimal]
    cuota_capital: Decimal
    interes_mensual: Decimal
    honorarios_cuota: Decimal
    gastos_judiciales: Decimal
    comision_pct: Decimal
    comision_total: Decimal
    ajuste: Decimal
    valor_cuota: Decimal
    total_intereses: Decimal
    total_honorarios: Decimal
    total_en_cuotas: Decimal
    gran_total: Decimal
    cuotas: List[FilaVista]
    texto: str


def _plan(datos: AcuerdoEntrada, request: Request) -> calculos.PlanAcuerdo:
    p = parametros_cobro(request)
    try:
        return calculos.calcular_acuerdo(
            capital=datos.capital, numero_cuotas=datos.numero_cuotas,
            tasa_mensual=datos.tasa_mensual, uf=datos.uf, modalidad=datos.modalidad,
            abono_inicial=datos.abono_inicial, gastos_judiciales=datos.gastos_judiciales,
            con_comision=datos.con_comision, comision_pct=p["comision_pct"],
            pct_judicial=p["pct_judicial"], redondeo=datos.redondeo,
            fecha_primera=datos.fecha_primera_cuota, dia_siguientes=datos.dia_siguientes,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


def _vista_plan(plan: calculos.PlanAcuerdo, datos: AcuerdoEntrada) -> PlanVista:
    campos = {k: v for k, v in plan.__dict__.items() if k not in ("cuotas", "honorarios_tramos")}
    return PlanVista(
        **campos,
        cuotas=[FilaVista(**f.__dict__) for f in plan.cuotas],
        texto=calculos.texto_acuerdo(plan, datos.fecha_pie, datos.dia_siguientes),
    )


@router.post("/api/calculadora/acuerdo", response_model=PlanVista, dependencies=solo_premium)
def simular_acuerdo(datos: AcuerdoEntrada, request: Request):
    return _vista_plan(_plan(datos, request), datos)


class AcuerdoCrear(AcuerdoEntrada):
    cobranza_id: UUID
    fecha_primera_cuota: date  # obligatoria para crear
    observaciones: Optional[str] = Field(None, max_length=2000)


@router.post("/api/calculadora/acuerdo/crear", response_model=AcuerdoDetalle,
             status_code=201, dependencies=solo_premium)
def crear_acuerdo_asistido(
    datos: AcuerdoCrear,
    request: Request,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """
    Crea el acuerdo con el plan calculado por el servidor (no se confía en
    montos enviados por el navegador). Cada cuota queda con su desglose.
    """
    cobranza = db.get(Cobranza, datos.cobranza_id)
    if cobranza is None:
        raise HTTPException(status_code=404, detail="Cobranza no encontrada")
    validar_sin_acuerdo_vigente(db, cobranza.id)

    plan = _plan(datos, request)
    texto = calculos.texto_acuerdo(plan, datos.fecha_pie, datos.dia_siguientes)
    nombre = "AVENIMIENTO" if plan.modalidad == "judicial" else "ACUERDO DE PAGO"

    acuerdo = AcuerdoPago(
        cobranza_id=cobranza.id,
        usuario_id=usuario.id,
        pie=plan.abono_inicial,
        monto_total_acordado=plan.gran_total,
        numero_cuotas=plan.numero_cuotas,
        dia_pago=datos.dia_siguientes or datos.fecha_primera_cuota.day,
        fecha_primera_cuota=datos.fecha_primera_cuota,
        fecha_termino=plan.cuotas[-1].fecha,
        capital=plan.capital,
        honorarios=plan.total_honorarios,
        intereses=plan.total_intereses,
        gastos_judiciales=plan.gastos_judiciales,
        observaciones="\n".join(x for x in (texto, datos.observaciones) if x),
    )
    acuerdo.cuotas = [
        Cuota(
            numero_cuota=f.numero, monto=f.total, fecha_vencimiento=f.fecha,
            capital=f.capital, intereses=f.intereses, honorarios=f.honorarios,
            gastos_judiciales=f.gastos_judiciales, comision=f.comision,
        )
        for f in plan.cuotas
    ]
    db.add(acuerdo)
    cobranza.estado = "acuerdo_pago"

    detalle = f"{nombre}: {texto}"
    if plan.modalidad == "extrajudicial" and plan.uf:
        detalle += f" Calculado con UF {plan.uf} y tasa {plan.tasa_mensual} % mensual."
    tipo = tipo_de_sistema(db, "acuerdo")
    db.add(Gestion(cobranza_id=cobranza.id, usuario_id=usuario.id,
                   tipo_id=tipo.id if tipo else None, descripcion=detalle))
    db.commit()
    db.refresh(acuerdo)
    return acuerdo

"""Schemas del módulo judicial: causas, trámites, embargos, gastos y ciclo de vida."""

from datetime import date, datetime
from decimal import Decimal
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Procedimiento = Literal[
    "ejecutivo", "notificacion_cheque", "notificacion_factura", "notificacion_letra",
    "confesion_deuda", "ordinario", "sumario", "exhorto", "liquidacion", "querella", "otro",
]
EtapaProcesal = Literal["demanda", "notificacion", "embargo", "defensa", "remate"]
Resultado = Literal[
    "pagada", "avenimiento_cumplido", "castigo", "desistida", "abandono", "prescrita",
    "archivada", "devuelta",
]
TipoBien = Literal["vehiculo", "inmueble", "cuenta_bancaria", "remuneraciones", "muebles", "otro"]
EstadoEmbargo = Literal["solicitado", "trabado", "frustrado", "retirado", "rematado", "alzado"]
TipoGasto = Literal[
    "receptor", "notificacion", "embargo", "fuerza_publica", "conservador", "copias",
    "publicacion", "martillero", "correo", "otro",
]


# ------------------------------------------------------------------ catálogos

class TribunalCreate(BaseModel):
    nombre: str = Field(..., min_length=3, max_length=150)
    ciudad: Optional[str] = Field(None, max_length=80)
    competencia: Literal["civil", "penal", "laboral", "corte", "otro"] = "civil"


class TribunalResponse(TribunalCreate):
    id: int
    activo: bool
    propio: bool
    model_config = ConfigDict(from_attributes=True)


class TipoTramiteBase(BaseModel):
    nombre: str = Field(..., min_length=2, max_length=150)
    etapa: Optional[EtapaProcesal] = None
    plazo_dias: Optional[int] = Field(None, ge=0, le=3650)
    siguiente_id: Optional[int] = None
    genera_gasto: bool = False
    alerta: bool = False
    nota: Optional[str] = Field(None, max_length=300)
    resultado: Optional[Resultado] = None


class TipoTramiteUpdate(BaseModel):
    nombre: Optional[str] = Field(None, min_length=2, max_length=150)
    etapa: Optional[EtapaProcesal] = None
    plazo_dias: Optional[int] = Field(None, ge=0, le=3650)
    siguiente_id: Optional[int] = None
    genera_gasto: Optional[bool] = None
    alerta: Optional[bool] = None
    nota: Optional[str] = Field(None, max_length=300)
    resultado: Optional[Resultado] = None
    activo: Optional[bool] = None


class TipoTramiteResponse(TipoTramiteBase):
    id: int
    codigo: Optional[str] = None
    orden: int
    activo: bool
    propio: bool
    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------ causas

class CausaDatos(BaseModel):
    rol: Optional[str] = Field(None, max_length=40)
    tribunal_id: Optional[int] = None
    procedimiento: Procedimiento = "ejecutivo"
    fecha_ingreso: Optional[date] = None
    cuantia: Optional[Decimal] = Field(None, ge=0, max_digits=15, decimal_places=2)
    caratula: Optional[str] = Field(None, max_length=250)
    abogado_id: Optional[UUID] = None
    procurador_id: Optional[UUID] = None
    observaciones: Optional[str] = Field(None, max_length=4000)


class CausaCreate(CausaDatos):
    """Presentar una demanda con una o varias cobranzas del mismo deudor y cliente."""
    cobranza_ids: List[UUID] = Field(..., min_length=1, max_length=50)


class CausaUpdate(BaseModel):
    rol: Optional[str] = Field(None, max_length=40)
    tribunal_id: Optional[int] = None
    procedimiento: Optional[Procedimiento] = None
    fecha_ingreso: Optional[date] = None
    cuantia: Optional[Decimal] = Field(None, ge=0, max_digits=15, decimal_places=2)
    caratula: Optional[str] = Field(None, max_length=250)
    abogado_id: Optional[UUID] = None
    procurador_id: Optional[UUID] = None
    observaciones: Optional[str] = Field(None, max_length=4000)
    # Corrección manual de la etapa (normalmente la mueven los trámites).
    etapa_procesal: Optional[EtapaProcesal] = None


class AgregarCobranza(BaseModel):
    cobranza_id: UUID


class TerminarCausa(BaseModel):
    resultado: Resultado
    fecha: Optional[date] = None
    motivo_cierre: Optional[str] = Field(None, max_length=30)
    nota: Optional[str] = Field(None, max_length=2000)


class CausaFila(BaseModel):
    """Una causa en la bandeja."""
    id: UUID
    rol: Optional[str] = None
    procedimiento: str
    etapa_procesal: str
    estado: str
    resultado: Optional[str] = None
    fecha_ingreso: date
    fecha_termino: Optional[date] = None
    cuantia: Optional[Decimal] = None
    caratula: Optional[str] = None
    tribunal: Optional[str] = None
    deudor: str
    deudor_rut: Optional[str] = None
    cliente: str
    abogado: Optional[str] = None
    procurador: Optional[str] = None
    ultima_fecha: Optional[date] = None
    ultimo_tramite: Optional[str] = None
    plazo_fecha: Optional[date] = None
    siguiente_nombre: Optional[str] = None
    numeros_cobranza: Optional[List[int]] = None
    dias_sin_movimiento: Optional[int] = None


class CobranzaEnCausa(BaseModel):
    id: UUID
    numero: int
    id_externo: Optional[str] = None
    tipo_documento: Optional[str] = None
    numero_documento: Optional[str] = None
    monto_original: Decimal
    monto_actual: Decimal
    estado: str
    model_config = ConfigDict(from_attributes=True)


class TramiteResponse(BaseModel):
    id: UUID
    causa_id: UUID
    tipo_id: Optional[int] = None
    tipo_nombre: Optional[str] = None
    fecha: date
    descripcion: Optional[str] = None
    plazo_fecha: Optional[date] = None
    siguiente_id: Optional[int] = None
    siguiente_nombre: Optional[str] = None
    usuario_nombre: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class EmbargoBase(BaseModel):
    tipo_bien: TipoBien
    descripcion: str = Field(..., min_length=2, max_length=300)
    estado: EstadoEmbargo = "trabado"
    fecha_traba: Optional[date] = None
    inscripcion: Optional[str] = Field(None, max_length=150)
    depositario: Optional[str] = Field(None, max_length=150)
    monto_tasacion: Optional[Decimal] = Field(None, ge=0, max_digits=15, decimal_places=2)
    fecha_remate: Optional[date] = None
    monto_remate: Optional[Decimal] = Field(None, ge=0, max_digits=15, decimal_places=2)
    observaciones: Optional[str] = Field(None, max_length=2000)


class EmbargoUpdate(BaseModel):
    tipo_bien: Optional[TipoBien] = None
    descripcion: Optional[str] = Field(None, min_length=2, max_length=300)
    estado: Optional[EstadoEmbargo] = None
    fecha_traba: Optional[date] = None
    inscripcion: Optional[str] = Field(None, max_length=150)
    depositario: Optional[str] = Field(None, max_length=150)
    monto_tasacion: Optional[Decimal] = Field(None, ge=0, max_digits=15, decimal_places=2)
    fecha_remate: Optional[date] = None
    monto_remate: Optional[Decimal] = Field(None, ge=0, max_digits=15, decimal_places=2)
    observaciones: Optional[str] = Field(None, max_length=2000)


class EmbargoResponse(EmbargoBase):
    id: UUID
    causa_id: UUID
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------ gastos

class GastoDatos(BaseModel):
    fecha: Optional[date] = None
    tipo: TipoGasto = "receptor"
    concepto: Optional[str] = Field(None, max_length=200)
    monto: Decimal = Field(..., gt=0, max_digits=15, decimal_places=2)
    proveedor: Optional[str] = Field(None, max_length=150)
    numero_boleta: Optional[str] = Field(None, max_length=50)


class GastoCreate(GastoDatos):
    concepto: str = Field(..., min_length=2, max_length=200)
    cobranza_id: Optional[UUID] = None
    causa_id: Optional[UUID] = None
    estado: Literal["por_rendir", "no_reembolsable"] = "por_rendir"
    observaciones: Optional[str] = Field(None, max_length=2000)


class GastoUpdate(BaseModel):
    fecha: Optional[date] = None
    tipo: Optional[TipoGasto] = None
    concepto: Optional[str] = Field(None, min_length=2, max_length=200)
    monto: Optional[Decimal] = Field(None, gt=0, max_digits=15, decimal_places=2)
    proveedor: Optional[str] = Field(None, max_length=150)
    numero_boleta: Optional[str] = Field(None, max_length=50)
    estado: Optional[Literal["por_rendir", "no_reembolsable", "anulado"]] = None
    observaciones: Optional[str] = Field(None, max_length=2000)


class GastoResponse(BaseModel):
    id: UUID
    cliente_id: UUID
    cliente_nombre: Optional[str] = None
    cobranza_id: Optional[UUID] = None
    numero_cobranza: Optional[int] = None
    causa_id: Optional[UUID] = None
    rol_causa: Optional[str] = None
    tramite_id: Optional[UUID] = None
    fecha: date
    tipo: str
    concepto: str
    monto: Decimal
    proveedor: Optional[str] = None
    numero_boleta: Optional[str] = None
    estado: str
    rendicion_id: Optional[UUID] = None
    numero_rendicion: Optional[int] = None
    fecha_reembolso: Optional[date] = None
    observaciones: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class TramiteCreate(BaseModel):
    """Registrar un trámite en un paso, con su gasto si corresponde."""
    tipo_id: Optional[int] = None  # vacío = observación
    fecha: Optional[date] = None
    descripcion: Optional[str] = Field(None, max_length=4000)
    plazo_fecha: Optional[date] = None  # a mano; si no, el del tipo
    sin_plazo: bool = False
    siguiente_id: Optional[int] = None
    gasto: Optional[GastoDatos] = None


class TramiteRegistrado(BaseModel):
    tramite: TramiteResponse
    etapa_procesal: str
    # Si el trámite suele cerrar la causa, se propone terminarla.
    propone_resultado: Optional[str] = None
    gasto_id: Optional[UUID] = None


class CausaDetalle(BaseModel):
    id: UUID
    rol: Optional[str] = None
    tribunal_id: Optional[int] = None
    tribunal: Optional[str] = None
    procedimiento: str
    procedimiento_nombre: str
    etapa_procesal: str
    estado: str
    resultado: Optional[str] = None
    fecha_ingreso: date
    fecha_termino: Optional[date] = None
    cuantia: Optional[Decimal] = None
    caratula: Optional[str] = None
    cliente_id: UUID
    cliente: str
    deudor_id: UUID
    deudor: str
    deudor_rut: Optional[str] = None
    abogado_id: Optional[UUID] = None
    abogado: Optional[str] = None
    procurador_id: Optional[UUID] = None
    procurador: Optional[str] = None
    observaciones: Optional[str] = None
    cobranzas: List[CobranzaEnCausa]
    tramites: List[TramiteResponse]
    embargos: List[EmbargoResponse]
    gastos: List[GastoResponse]
    plazo_fecha: Optional[date] = None
    siguiente_id: Optional[int] = None
    siguiente_nombre: Optional[str] = None
    dias_sin_movimiento: int
    riesgo_abandono: bool
    total_gastos: Decimal


class ResumenJudicial(BaseModel):
    vigentes: int
    por_etapa: dict
    plazos_vencidos: int
    plazos_hoy: int
    plazos_semana: int
    riesgo_abandono: int
    para_demanda: int


class CobranzaParaDemanda(BaseModel):
    id: UUID
    numero: int
    monto_actual: Decimal
    fecha_ingreso: date
    etapa: str
    etapa_desde: date
    tipo_documento: Optional[str] = None
    fecha_vencimiento_documento: Optional[date] = None
    deudor: str
    deudor_rut: Optional[str] = None
    cliente: str
    dias_para_demanda: Optional[int] = None
    dias_en_cartera: int
    ultima_gestion: Optional[date] = None
    fecha_prescripcion: Optional[date] = None


class ParaDemanda(BaseModel):
    preparacion: List[CobranzaParaDemanda]
    sugeridas: List[CobranzaParaDemanda]


class RendicionCreate(BaseModel):
    gasto_ids: List[UUID] = Field(..., min_length=1, max_length=2000)
    fecha: Optional[date] = None
    observaciones: Optional[str] = Field(None, max_length=2000)


class ReembolsoMasivo(BaseModel):
    gasto_ids: List[UUID] = Field(..., min_length=1, max_length=2000)
    fecha: Optional[date] = None


class PagoRendicion(BaseModel):
    fecha_pago: Optional[date] = None


class RendicionResponse(BaseModel):
    id: UUID
    numero: int
    cliente_id: UUID
    cliente_nombre: Optional[str] = None
    fecha: date
    total: Decimal
    estado: str
    fecha_pago: Optional[date] = None
    observaciones: Optional[str] = None
    cantidad: int = 0
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class RendicionDetalle(RendicionResponse):
    gastos: List[GastoResponse]


class ResumenGastosCliente(BaseModel):
    cliente_id: UUID
    cliente: str
    por_rendir: Decimal
    cantidad_por_rendir: int
    rendido: Decimal
    reembolsado: Decimal
    total_adeudado: Decimal


# ------------------------------------------------------------- ciclo de vida

class PasoCiclo(BaseModel):
    clave: str
    nombre: str
    grupo: Optional[str] = None
    estado: Literal["hecho", "actual", "pendiente", "omitido"]


class CausaEnCiclo(BaseModel):
    id: UUID
    rol: Optional[str] = None
    procedimiento: str
    etapa_procesal: str
    estado: str
    resultado: Optional[str] = None
    fecha_ingreso: date
    fecha_termino: Optional[date] = None
    tribunal: Optional[str] = None


class CambioEtapaResponse(BaseModel):
    etapa_anterior: Optional[str] = None
    etapa_nueva: str
    motivo: Optional[str] = None
    created_at: datetime
    usuario: Optional[str] = None


class CicloVida(BaseModel):
    cobranza_id: UUID
    etapa: str
    etapa_desde: date
    dias_en_etapa: Optional[int] = None
    paso_actual: str
    pasos: List[PasoCiclo]
    estado: str
    motivo_cierre: Optional[str] = None
    motivo_cierre_nombre: Optional[str] = None
    fecha_cierre: Optional[date] = None
    fecha_prescripcion: Optional[date] = None
    prescripcion_proxima: bool
    causas: List[CausaEnCiclo]
    historial: List[CambioEtapaResponse]


class CambiarEtapa(BaseModel):
    etapa: Literal["extrajudicial", "para_demanda"]
    motivo: Optional[str] = Field(None, max_length=300)

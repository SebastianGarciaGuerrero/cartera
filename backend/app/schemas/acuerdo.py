"""
Schemas Pydantic para acuerdos de pago y sus cuotas.

Las cuotas NO se reciben en el Create: las genera el backend automáticamente
a partir de monto_total_acordado, pie, numero_cuotas y fecha_primera_cuota.

El único cambio permitido sobre un acuerdo existente es su estado y la firma
del cliente (AcuerdoEstadoUpdate). Montos y cuotas son inmutables: una
renegociación crea un acuerdo nuevo.
"""

from uuid import UUID
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator


EstadoAcuerdo = Literal["vigente", "cumplido", "incumplido", "renegociado"]
TipoPago = Literal["extrajudicial", "abonos"]
FirmaCliente = Literal["sin_firmar", "pendiente", "firmado_confirmado"]
EstadoCuota = Literal["pendiente", "pagada", "vencida", "pagada_parcial"]


class CuotaResponse(BaseModel):
    """Una cuota generada del acuerdo (solo lectura desde aquí)."""
    id: UUID
    acuerdo_id: UUID
    numero_cuota: int
    monto: Decimal
    fecha_vencimiento: date
    monto_pagado: Decimal
    estado: EstadoCuota
    # Desglose (solo en acuerdos creados con la calculadora)
    capital: Optional[Decimal] = None
    intereses: Optional[Decimal] = None
    honorarios: Optional[Decimal] = None
    gastos_judiciales: Optional[Decimal] = None
    comision: Optional[Decimal] = None

    model_config = ConfigDict(from_attributes=True)


class AcuerdoBase(BaseModel):
    """
    Campos que definen el acuerdo al crearlo.
    usuario_id NO se envía: se deduce del token del usuario autenticado.
    """
    cobranza_id: UUID

    fecha_acuerdo: Optional[date] = None
    pie: Decimal = Field(Decimal("0"), ge=0, max_digits=15, decimal_places=2)
    monto_total_acordado: Decimal = Field(..., gt=0, max_digits=15, decimal_places=2)
    numero_cuotas: int = Field(1, ge=1, le=120)
    dia_pago: Optional[int] = Field(None, ge=1, le=31)
    fecha_primera_cuota: date

    # Desglose para rendición
    capital: Decimal = Field(Decimal("0"), ge=0, max_digits=15, decimal_places=2)
    honorarios: Decimal = Field(Decimal("0"), ge=0, max_digits=15, decimal_places=2)
    intereses: Decimal = Field(Decimal("0"), ge=0, max_digits=15, decimal_places=2)
    gastos_judiciales: Decimal = Field(Decimal("0"), ge=0, max_digits=15, decimal_places=2)

    tipo_pago: TipoPago = "extrajudicial"
    firma_cliente: FirmaCliente = "sin_firmar"
    fecha_firma: Optional[date] = None
    observaciones: Optional[str] = None


class CuotaManual(BaseModel):
    """Una cuota escrita a mano (fecha y monto propios)."""
    fecha_vencimiento: date
    monto: Decimal = Field(..., gt=0, max_digits=15, decimal_places=2)


def validar_cuotas_manuales(datos):
    """
    Cuotas a mano: deben sumar exactamente lo que queda después del pie y
    venir en orden de fecha. El N° de cuotas y la primera fecha salen de ellas.
    """
    if not datos.cuotas:
        return datos
    total = sum((c.monto for c in datos.cuotas), Decimal(0))
    esperado = Decimal(datos.monto_total_acordado) - Decimal(datos.pie or 0)
    if total != esperado:
        raise ValueError(
            f"Las cuotas suman {total:,.0f} y deben sumar {esperado:,.0f} "
            "(monto total menos el pie).".replace(",", ".")
        )
    fechas = [c.fecha_vencimiento for c in datos.cuotas]
    if fechas != sorted(fechas):
        raise ValueError("Las cuotas deben ir en orden de fecha de vencimiento.")
    datos.numero_cuotas = len(datos.cuotas)
    datos.fecha_primera_cuota = fechas[0]
    return datos


class AcuerdoCreate(AcuerdoBase):
    """
    Datos para crear un acuerdo. El backend:
    - genera las cuotas automáticamente (o usa las que vienen escritas a mano
      en `cuotas`, si se mandan),
    - calcula fecha_termino (vencimiento de la última cuota),
    - lo crea en estado 'vigente'.
    """
    cuotas: Optional[List[CuotaManual]] = Field(None, min_length=1, max_length=120)

    _cuotas = model_validator(mode="after")(validar_cuotas_manuales)


class AcuerdoEstadoUpdate(BaseModel):
    """
    Único cambio permitido sobre un acuerdo existente: su estado y la firma
    de la clínica. NO se editan montos ni cuotas.
    """
    estado: Optional[EstadoAcuerdo] = None
    firma_cliente: Optional[FirmaCliente] = None
    fecha_firma: Optional[date] = None
    observaciones: Optional[str] = None


class AcuerdoResponse(AcuerdoBase):
    """Acuerdo tal como se devuelve (datos planos)."""
    id: UUID
    usuario_id: UUID  # quién lo registró (vino del token al crearlo)
    estado: EstadoAcuerdo
    fecha_termino: Optional[date] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AcuerdoDetalle(AcuerdoResponse):
    """Acuerdo con su calendario de cuotas anidado."""
    cuotas: List[CuotaResponse] = Field(default_factory=list)

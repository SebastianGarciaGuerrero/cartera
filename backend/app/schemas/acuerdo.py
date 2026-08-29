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
from pydantic import BaseModel, Field, ConfigDict


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


class AcuerdoCreate(AcuerdoBase):
    """
    Datos para crear un acuerdo. El backend:
    - genera las cuotas automáticamente,
    - calcula fecha_termino (vencimiento de la última cuota),
    - lo crea en estado 'vigente'.
    """
    pass


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

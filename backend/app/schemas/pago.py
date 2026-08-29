"""
Schemas Pydantic para pagos.

Los pagos son INMUTABLES: no existe PagoUpdate ni endpoint PUT/DELETE.

Desglose (capital + honorarios + intereses): si se
informa (suma > 0), debe cuadrar exactamente con 'monto'. Se puede omitir
(quedan en 0) para pagos simples donde todavía no se separa el desglose.
"""

from uuid import UUID
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator


FormaPago = Literal[
    "transferencia", "cheque", "efectivo", "deposito",
    "flow", "presencial", "bonificacion", "otro",
]
EstadoPago = Literal["pagado", "abono", "cuota", "bonificacion"]


class PagoBase(BaseModel):
    """
    Campos de un pago al registrarlo.
    usuario_id NO se envía: se deduce del token del usuario autenticado.
    """
    cobranza_id: UUID
    cuota_id: Optional[UUID] = None  # NULL = pago directo sin cuota

    fecha_pago: Optional[date] = None
    monto: Decimal = Field(..., gt=0, max_digits=15, decimal_places=2)

    capital: Decimal = Field(Decimal("0"), ge=0, max_digits=15, decimal_places=2)
    honorarios: Decimal = Field(Decimal("0"), ge=0, max_digits=15, decimal_places=2)
    intereses: Decimal = Field(Decimal("0"), ge=0, max_digits=15, decimal_places=2)
    gastos_judiciales: Decimal = Field(Decimal("0"), ge=0, max_digits=15, decimal_places=2)

    forma_pago: Optional[FormaPago] = None
    numero_comprobante: Optional[str] = Field(None, max_length=100)
    estado_pago: EstadoPago = "pagado"
    descripcion_estado: Optional[str] = None
    observaciones: Optional[str] = None


class PagoCreate(PagoBase):
    """Datos para registrar un pago. POST /api/pagos."""

    @model_validator(mode="after")
    def _validar_desglose(self):
        """Si se informó desglose, la suma debe igualar el monto total."""
        suma = (self.capital + self.honorarios
                + self.intereses + self.gastos_judiciales)
        if suma > 0 and suma != self.monto:
            raise ValueError(
                f"El desglose (capital + honorarios + interés + gastos = {suma}) "
                f"debe sumar exactamente el monto del pago ({self.monto})."
            )
        return self


class PagoResponse(PagoBase):
    """Pago tal como se devuelve al frontend."""
    id: UUID
    usuario_id: UUID  # quién lo registró (vino del token al crearlo)
    fecha_pago: date
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

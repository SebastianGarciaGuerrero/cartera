"""
Schemas Pydantic para gestiones y tipos de gestión.

OJO: las gestiones son INMUTABLES. Por eso NO existe GestionUpdate ni
endpoint PUT/DELETE. Solo se listan, se obtienen y se crean.
"""

from uuid import UUID
from datetime import date, datetime
from decimal import Decimal
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, ConfigDict, model_validator

from app.schemas.acuerdo import CuotaManual, validar_cuotas_manuales


class TipoGestionResponse(BaseModel):
    """Un tipo del catálogo (para poblar selects y mostrar el nombre)."""
    id: int
    nombre: str
    codigo: Optional[str] = None     # solo los tipos de sistema
    categoria: str = "otro"          # contacto / pago / negativo / judicial / otro
    activo: bool
    propio: bool = False             # creado por la organización (editable)

    model_config = ConfigDict(from_attributes=True)


class GestionBase(BaseModel):
    """
    Campos de una gestión al registrarla.
    OJO: usuario_id NO se envía — se deduce del token del usuario autenticado.
    """
    cobranza_id: UUID
    tipo_id: Optional[int] = None
    descripcion: str = Field(..., min_length=1)
    # Si no se envía, PostgreSQL pone NOW(). Permite registrar gestiones con
    # fecha pasada (ej. cargar una llamada de ayer).
    fecha_gestion: Optional[datetime] = None
    fecha_proximo_contacto: Optional[date] = None


class GestionCreate(GestionBase):
    """Datos para registrar una gestión nueva. POST /api/gestiones."""
    pass


class GestionResponse(GestionBase):
    """Gestión tal como se devuelve (datos planos)."""
    id: UUID
    usuario_id: UUID  # quién la registró (vino del token al crearla)
    usuario_nombre: Optional[str] = None  # nombre legible de quien la registró
    es_masivo: bool = False  # True si vino de una carga masiva de gestiones
    fecha_gestion: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class GestionDetalle(GestionResponse):
    """Gestión con el tipo anidado (nombre legible del tipo)."""
    tipo: Optional[TipoGestionResponse] = None


# ------------------------------------------------------------ gestión en un paso

class PromesaEntrada(BaseModel):
    fecha: date
    monto: Optional[Decimal] = Field(None, gt=0, max_digits=15, decimal_places=2)


class TerminosAcuerdo(BaseModel):
    """Los términos de un acuerdo, sin la cobranza (va en la gestión)."""
    monto_total_acordado: Decimal = Field(..., gt=0, max_digits=15, decimal_places=2)
    pie: Decimal = Field(Decimal("0"), ge=0, max_digits=15, decimal_places=2)
    numero_cuotas: int = Field(1, ge=1, le=120)
    fecha_primera_cuota: date
    dia_pago: Optional[int] = Field(None, ge=1, le=31)
    cuotas: Optional[List[CuotaManual]] = Field(None, min_length=1, max_length=120)
    observaciones: Optional[str] = Field(None, max_length=2000)

    _cuotas = model_validator(mode="after")(validar_cuotas_manuales)


class GestionCompleta(BaseModel):
    """
    Lo que pasó y su resultado, en un solo envío:
      gestion → solo la gestión; promesa → con fecha (y monto) prometidos;
      acuerdo → crea el acuerdo con sus cuotas.
    `tipo_id` es el tipo de gestión, o el canal (llamada, WhatsApp...) cuando
    el resultado es promesa o acuerdo.
    """
    cobranza_id: UUID
    resultado: Literal["gestion", "promesa", "acuerdo"] = "gestion"
    tipo_id: Optional[int] = None
    descripcion: Optional[str] = Field(None, max_length=5000)
    fecha_proximo_contacto: Optional[date] = None
    promesa: Optional[PromesaEntrada] = None
    acuerdo: Optional[TerminosAcuerdo] = None

    @model_validator(mode="after")
    def _segun_resultado(self):
        if self.resultado == "gestion" and not (self.descripcion or "").strip():
            raise ValueError("Escribe qué pasó en la gestión.")
        if self.resultado == "promesa" and self.promesa is None:
            raise ValueError("Indica la fecha de la promesa de pago.")
        if self.resultado == "acuerdo" and self.acuerdo is None:
            raise ValueError("Faltan los términos del acuerdo.")
        return self

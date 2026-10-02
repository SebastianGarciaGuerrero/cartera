"""
Schemas Pydantic para gestiones y tipos de gestión.

OJO: las gestiones son INMUTABLES. Por eso NO existe GestionUpdate ni
endpoint PUT/DELETE. Solo se listan, se obtienen y se crean.
"""

from uuid import UUID
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


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
    usuario_nombre: Optional[str] = None  # nombre legible (ej. "GRV")
    es_masivo: bool = False  # True si vino de una carga masiva de gestiones
    fecha_gestion: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class GestionDetalle(GestionResponse):
    """Gestión con el tipo anidado (nombre legible del tipo)."""
    tipo: Optional[TipoGestionResponse] = None

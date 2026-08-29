"""
Schemas Pydantic para Filial.
"""

from uuid import UUID
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class FilialBase(BaseModel):
    """Campos editables de una filial."""
    cliente_id: UUID
    nombre: str = Field(..., min_length=1, max_length=100)


class FilialCreate(FilialBase):
    """Datos para crear una filial nueva."""
    pass


class FilialUpdate(BaseModel):
    """Datos para actualizar (todos opcionales)."""
    nombre: Optional[str] = Field(None, min_length=1, max_length=100)
    activo: Optional[bool] = None


class FilialResponse(FilialBase):
    """Datos que devolvemos al frontend."""
    id: int
    activo: bool
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class FilialConCliente(FilialResponse):
    """
    Versión extendida con datos del cliente incluidos.
    Útil para listados donde quieres ver "Cliente - Iquique" sin hacer otra query.
    """
    cliente_razon_social: Optional[str] = None
    cliente_rut: Optional[str] = None
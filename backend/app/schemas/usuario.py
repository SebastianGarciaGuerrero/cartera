"""
Schemas Pydantic para Usuario.

REGLA INVIOLABLE: password_hash, el secreto 2FA y los códigos de
recuperación NUNCA se incluyen en una respuesta.
"""

from uuid import UUID
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, EmailStr, Field, ConfigDict, computed_field


class UsuarioCreate(BaseModel):
    """
    El ADMIN crea un usuario de su organización. Dos formas:
      - sin password: se le envía un correo de invitación para que elija la
        suya (recomendado: el admin nunca conoce la clave).
      - con password inicial: queda marcada para cambiarla al entrar.
    """
    nombre: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    rol_id: int
    password: Optional[str] = Field(None, max_length=128)
    # Obligatorio para el rol 'mandante' (portal de clientes).
    cliente_id: Optional[UUID] = None


class UsuarioUpdate(BaseModel):
    """Cambios que el ADMIN puede hacer sobre un usuario (sin contraseña)."""
    nombre: Optional[str] = Field(None, min_length=1, max_length=100)
    email: Optional[EmailStr] = None
    rol_id: Optional[int] = None
    cliente_id: Optional[UUID] = None
    activo: Optional[bool] = None  # desactivar = ya no puede entrar


class PasswordReset(BaseModel):
    """El ADMIN fija una contraseña temporal (el usuario la cambia al entrar)."""
    password_nueva: str = Field(..., max_length=128)


class UsuarioResponse(BaseModel):
    """Datos seguros de un usuario para devolver por la API."""
    id: UUID
    nombre: str
    email: str
    rol_id: int
    rol_nombre: Optional[str] = None
    cliente_id: Optional[UUID] = None
    activo: bool
    mfa_activo: bool = False
    debe_cambiar_password: bool = False
    bloqueado_hasta: Optional[datetime] = None
    ultimo_acceso: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @computed_field
    @property
    def bloqueado(self) -> bool:
        return bool(self.bloqueado_hasta and self.bloqueado_hasta > datetime.now(timezone.utc))

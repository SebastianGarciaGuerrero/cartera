"""
Schemas Pydantic de autenticación y cuenta propia.
"""

from typing import List, Optional
from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class LoginEntrada(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=256)


class MfaEntrada(BaseModel):
    mfa_token: str
    codigo: str = Field(..., min_length=6, max_length=20)  # TOTP o código de recuperación


class OrganizacionActual(BaseModel):
    id: UUID
    nombre: str
    plan: str
    estado: str
    funciones: List[str]
    etiquetas: dict = {}


class UsuarioActual(BaseModel):
    id: UUID
    nombre: str
    email: EmailStr
    rol_id: int
    rol: str
    cliente_id: Optional[UUID] = None
    mfa_activo: bool
    debe_cambiar_password: bool
    organizacion: OrganizacionActual


class TokenRespuesta(BaseModel):
    """Login completo: access token (para el header) + datos del usuario."""
    access_token: str
    token_type: str = "bearer"
    expira_en: int  # segundos
    usuario: UsuarioActual


class MfaPendiente(BaseModel):
    """La contraseña era correcta pero falta el segundo factor."""
    requiere_mfa: bool = True
    mfa_token: str


class CambiarPassword(BaseModel):
    password_actual: str
    password_nueva: str = Field(..., max_length=128)


class RecuperarEntrada(BaseModel):
    email: EmailStr


class RestablecerEntrada(BaseModel):
    token: str = Field(..., min_length=20, max_length=200)
    password_nueva: str = Field(..., max_length=128)


class MfaInicio(BaseModel):
    qr: str              # data URI SVG
    secreto: str         # para ingresarlo a mano en la app
    uri: str


class MfaConfirmar(BaseModel):
    codigo: str = Field(..., min_length=6, max_length=6)


class MfaDesactivar(BaseModel):
    password: str
    codigo: str = Field(..., min_length=6, max_length=20)


class CodigosRecuperacion(BaseModel):
    codigos: List[str]


class SesionActiva(BaseModel):
    id: UUID
    creada_at: datetime
    ultimo_uso_at: datetime
    ip: Optional[str] = None
    user_agent: Optional[str] = None
    actual: bool = False

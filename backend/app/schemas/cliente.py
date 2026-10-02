"""
Schemas Pydantic para la entidad Cliente.
Definen qué datos entran (input) y qué datos salen (output) de la API.

Por qué tener schemas separados de los modelos:
- Los modelos (SQLAlchemy) representan la tabla completa.
- Los schemas (Pydantic) representan el contrato con el frontend.
- A veces no quieres exponer todos los campos (ej. timestamps internos).
- A veces aceptas menos campos al crear que los que tiene la tabla.
"""

from uuid import UUID
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field, ConfigDict

from app.rut import Rut


class ClienteBase(BaseModel):
    """
    Campos comunes que comparten Create y Update.
    Estos son los datos "editables" por el usuario.
    """
    rut: str = Field(..., min_length=8, max_length=12, examples=["96570220-7"])
    razon_social: str = Field(..., min_length=1, max_length=200)
    nombre_fantasia: Optional[str] = Field(None, max_length=200)
    direccion: Optional[str] = None
    comuna: Optional[str] = Field(None, max_length=100)
    ciudad: Optional[str] = Field(None, max_length=100)
    telefono: Optional[str] = Field(None, max_length=50)
    email: Optional[EmailStr] = None  # EmailStr valida formato de email automáticamente


class ClienteCreate(ClienteBase):
    """
    Datos necesarios para crear un cliente nuevo.
    POST /api/clientes recibe un JSON con esta estructura.
    El RUT se valida (dígito verificador) y se guarda normalizado.
    """
    rut: Rut = Field(..., examples=["96.570.220-7"])


class ClienteUpdate(BaseModel):
    """
    Datos para actualizar un cliente. Todos opcionales porque
    se pueden actualizar solo algunos campos.
    PUT /api/clientes/{id} recibe esto.
    """
    razon_social: Optional[str] = None
    nombre_fantasia: Optional[str] = None
    direccion: Optional[str] = None
    comuna: Optional[str] = None
    ciudad: Optional[str] = None
    telefono: Optional[str] = None
    email: Optional[EmailStr] = None
    activo: Optional[bool] = None
    # NOTA: el RUT no se puede cambiar. Es identificador.


class ClienteResponse(ClienteBase):
    """
    Datos que devolvemos al frontend.
    Incluye campos generados por el sistema (id, timestamps).
    GET /api/clientes devuelve una lista de estos objetos.
    """
    id: UUID
    activo: bool
    created_at: datetime
    updated_at: datetime
    
    # Esto le dice a Pydantic que puede leer atributos de objetos SQLAlchemy
    # (no solo de diccionarios). Permite hacer: ClienteResponse.model_validate(cliente_db)
    model_config = ConfigDict(from_attributes=True)
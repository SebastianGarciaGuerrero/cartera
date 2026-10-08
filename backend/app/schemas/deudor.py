"""
Schemas Pydantic para la entidad Deudor.
Definen qué datos entran (input) y qué datos salen (output) de la API.
"""

from uuid import UUID
from datetime import date, datetime
from typing import Optional, Literal, List
from pydantic import BaseModel, Field, ConfigDict

from app.rut import Rut


# ============================================================
# Contactos del deudor (teléfonos, emails, WhatsApp, etc.)
# ============================================================

class ContactoBase(BaseModel):
    """Campos editables de un contacto."""
    tipo: Literal["telefono", "celular", "email", "whatsapp", "otro"]
    valor: str = Field(..., min_length=1, max_length=200)


class ContactoCreate(ContactoBase):
    """Datos para crear un contacto nuevo."""
    pass


class ContactoResponse(ContactoBase):
    """Contacto tal como se devuelve al frontend."""
    id: UUID
    deudor_id: UUID
    activo: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DeudorBase(BaseModel):
    """
    Campos comunes que comparten Create y Update.
    Estos son los datos "editables" por el usuario.
    """
    rut: str = Field(..., min_length=8, max_length=12, examples=["12345678-9"])
    tipo: Literal["natural", "juridica"] = "natural"
    nombre: str = Field(..., min_length=1, max_length=200)
    fecha_nacimiento: Optional[date] = None
    estado_civil: Optional[str] = Field(None, max_length=30)
    nacionalidad: Optional[str] = Field("Chilena", max_length=60)

    direccion: Optional[str] = None
    departamento: Optional[str] = Field(None, max_length=50)
    comuna: Optional[str] = Field(None, max_length=100)
    ciudad: Optional[str] = Field(None, max_length=100)
    region: Optional[str] = Field(None, max_length=100)

    empleador: Optional[str] = Field(None, max_length=200)
    cargo: Optional[str] = Field(None, max_length=100)
    telefono_trabajo: Optional[str] = Field(None, max_length=50)
    direccion_trabajo: Optional[str] = None

    contacto_alt_nombre: Optional[str] = Field(None, max_length=200)
    contacto_alt_relacion: Optional[str] = Field(None, max_length=80)
    contacto_alt_telefono: Optional[str] = Field(None, max_length=50)

    en_boletin_comercial: bool = False  # DICOM u otro boletín comercial
    # Campos personalizados de la organización (clave → valor).
    datos_extra: dict = Field(default_factory=dict)
    observaciones: Optional[str] = None


class DeudorCreate(DeudorBase):
    """
    Datos necesarios para crear un deudor nuevo.
    POST /api/deudores recibe un JSON con esta estructura.
    Opcionalmente puede traer una lista de contactos que se crean
    en la misma transacción que el deudor.
    """
    rut: Rut = Field(..., examples=["12.345.678-5"])  # se valida y normaliza
    contactos: List[ContactoCreate] = Field(default_factory=list)


class DeudorUpdate(BaseModel):
    """
    Datos para actualizar un deudor. Todos opcionales porque
    se pueden actualizar solo algunos campos.
    PUT /api/deudores/{id} recibe esto.
    """
    tipo: Optional[Literal["natural", "juridica"]] = None
    nombre: Optional[str] = None
    fecha_nacimiento: Optional[date] = None
    estado_civil: Optional[str] = None
    nacionalidad: Optional[str] = None

    direccion: Optional[str] = None
    departamento: Optional[str] = None
    comuna: Optional[str] = None
    ciudad: Optional[str] = None
    region: Optional[str] = None

    empleador: Optional[str] = None
    cargo: Optional[str] = None
    telefono_trabajo: Optional[str] = None
    direccion_trabajo: Optional[str] = None

    contacto_alt_nombre: Optional[str] = None
    contacto_alt_relacion: Optional[str] = None
    contacto_alt_telefono: Optional[str] = None

    en_boletin_comercial: Optional[bool] = None
    datos_extra: Optional[dict] = None
    observaciones: Optional[str] = None
    # NOTA: el RUT no se puede cambiar. Es identificador.


class DeudorResponse(DeudorBase):
    """
    Datos que devolvemos al frontend.
    Incluye campos generados por el sistema (id, timestamps).
    GET /api/deudores devuelve una lista de estos objetos.
    """
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DeudorDetalle(DeudorResponse):
    """
    Igual que DeudorResponse pero incluye la lista de contactos del deudor.
    Se usa en GET /api/deudores/{id} (ficha completa del deudor).
    """
    contactos: List[ContactoResponse] = Field(default_factory=list)


class DeudorBusqueda(DeudorResponse):
    """Resultado de búsqueda: el deudor más un resumen de sus deudas."""
    total_cobranzas: int = 0
    cobranzas_abiertas: int = 0
    saldo_abierto: float = 0

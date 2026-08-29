"""
Schemas Pydantic para 'empresa' (los datos de la empresa que usa el sistema).

Solo hay lectura y actualización: la fila existe siempre (la crea el DDL), no
se crea ni se borra desde la API.
"""

from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class EmpresaUpdate(BaseModel):
    """
    Todos los campos son opcionales: la pantalla puede mandar solo lo que
    cambió. Los que no vienen quedan como estaban.
    """
    razon_social: Optional[str] = Field(None, min_length=1, max_length=200)
    nombre_fantasia: Optional[str] = Field(None, max_length=100)
    rut: Optional[str] = Field(None, max_length=12)

    wordmark: Optional[str] = Field(None, min_length=1, max_length=100)
    bajada: Optional[str] = Field(None, max_length=150)
    firma_documentos: Optional[str] = Field(None, max_length=200)

    direccion: Optional[str] = Field(None, max_length=200)
    ciudad: Optional[str] = Field(None, max_length=100)
    horario_atencion: Optional[str] = Field(None, max_length=120)
    telefonos: Optional[str] = Field(None, max_length=120)
    emails: Optional[str] = Field(None, max_length=200)
    sitio_web: Optional[str] = Field(None, max_length=120)

    instrucciones_pago: Optional[str] = None


class EmpresaResponse(BaseModel):
    """Lo que devuelve la API. Lo consumen la barra lateral y los Word."""
    razon_social: str
    nombre_fantasia: Optional[str] = None
    rut: Optional[str] = None

    wordmark: str
    bajada: Optional[str] = None
    firma_documentos: Optional[str] = None

    direccion: Optional[str] = None
    ciudad: Optional[str] = None
    horario_atencion: Optional[str] = None
    telefonos: Optional[str] = None
    emails: Optional[str] = None
    sitio_web: Optional[str] = None

    instrucciones_pago: Optional[str] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

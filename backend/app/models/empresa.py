"""
Modelo SQLAlchemy para 'empresa': los datos institucionales de cada
organización (membrete de los Word, firma, dirección, fonos, formas de pago).

Una fila por organización (organizacion_id es la clave primaria). Cada
estudio la edita desde Configuración → Mi empresa, sin tocar código.
"""

from sqlalchemy import Column, String, Text, TIMESTAMP, ForeignKey, LargeBinary, text
from sqlalchemy.orm import deferred
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base
from app.tenancy import TenantMixin


class Empresa(TenantMixin, Base):
    __tablename__ = "empresa"

    organizacion_id = Column(
        UUID(as_uuid=True), ForeignKey("organizaciones.id"), primary_key=True
    )

    # Identidad legal
    razon_social = Column(String(200), nullable=False)
    nombre_fantasia = Column(String(100))
    rut = Column(String(12))

    # Membrete de los documentos
    wordmark = Column(String(100), nullable=False)
    bajada = Column(String(150))
    firma_documentos = Column(String(200))

    # Contacto (pie de las cartas)
    direccion = Column(String(200))
    ciudad = Column(String(100))
    horario_atencion = Column(String(120))
    telefonos = Column(String(120))
    emails = Column(String(200))
    sitio_web = Column(String(120))

    # Formas de pago del estado de cuenta (texto libre, una por línea)
    instrucciones_pago = Column(Text)

    # Logo (PNG/JPG, máx. 1 MB). Diferido: solo se lee cuando se pide.
    logo = deferred(Column(LargeBinary))
    logo_tipo = Column(String(30))
    logo_actualizado_at = Column(TIMESTAMP(timezone=True))

    updated_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))

    @property
    def tiene_logo(self) -> bool:
        return self.logo_tipo is not None

    def __repr__(self):
        return f"<Empresa(razon_social='{self.razon_social}')>"

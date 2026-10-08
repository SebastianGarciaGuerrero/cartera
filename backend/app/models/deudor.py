"""
Modelo SQLAlchemy para la tabla 'deudores'.
Representa a la persona o empresa que firmó el pagaré: a quien se le cobra.
Otras personas ligadas a la deuda (aval, codeudor, paciente...) están en 'terceros'.
Los teléfonos/emails/WhatsApp del deudor viven en 'contactos_deudor', no aquí.
"""

from sqlalchemy import Column, String, Boolean, Text, Date, TIMESTAMP, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.database import Base
from app.tenancy import TenantMixin


class Deudor(TenantMixin, Base):
    """
    Mapea la tabla 'deudores' de PostgreSQL a una clase Python.
    El RUT es la llave maestra: agrupa todas las cobranzas de una misma persona.
    """

    __tablename__ = "deudores"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()")
    )

    # Identificación
    rut = Column(String(12), nullable=False)  # único por organización
    tipo = Column(String(10), nullable=False, server_default=text("'natural'"))
    nombre = Column(String(200), nullable=False)
    fecha_nacimiento = Column(Date)
    estado_civil = Column(String(30))
    nacionalidad = Column(String(60), server_default=text("'Chilena'"))

    # Dirección
    direccion = Column(Text)
    departamento = Column(String(50))
    comuna = Column(String(100))
    ciudad = Column(String(100))
    region = Column(String(100))

    # Datos laborales
    empleador = Column(String(200))
    cargo = Column(String(100))
    telefono_trabajo = Column(String(50))
    direccion_trabajo = Column(Text)

    # Contacto alternativo (un familiar o conocido que ayuda a ubicarlo)
    contacto_alt_nombre = Column(String(200))
    contacto_alt_relacion = Column(String(80))
    contacto_alt_telefono = Column(String(50))

    # Estado
    en_boletin_comercial = Column(Boolean, server_default=text("false"))  # DICOM u otro boletín
    # Valores de los campos personalizados que defina la organización.
    datos_extra = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    observaciones = Column(Text)

    created_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))
    updated_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))

    # Relationship: deudor.contactos devuelve la lista de ContactoDeudor.
    # cascade="all, delete-orphan" => si se borra el deudor, sus contactos
    # se borran con él (coincide con el ON DELETE CASCADE de la DB).
    contactos = relationship(
        "ContactoDeudor",
        back_populates="deudor",
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        """Cómo se ve el objeto al imprimirlo (útil para debugging)."""
        return f"<Deudor(rut={self.rut}, nombre='{self.nombre}')>"


class ContactoDeudor(TenantMixin, Base):
    """
    Mapea la tabla 'contactos_deudor': teléfonos, celulares, emails y
    WhatsApp de un deudor. Un deudor puede tener N contactos (sin límite).
    A diferencia del deudor, el contacto SÍ tiene soft-delete ('activo').
    """

    __tablename__ = "contactos_deudor"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()")
    )

    # ON DELETE CASCADE: si se elimina el deudor, sus contactos también.
    deudor_id = Column(
        UUID(as_uuid=True),
        ForeignKey("deudores.id", ondelete="CASCADE"),
        nullable=False
    )

    tipo = Column(String(20), nullable=False)  # telefono/celular/email/whatsapp/otro
    valor = Column(String(200), nullable=False)
    activo = Column(Boolean, server_default=text("true"))
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))

    # Navegación inversa: contacto.deudor devuelve el objeto Deudor.
    deudor = relationship("Deudor", back_populates="contactos")

    def __repr__(self):
        return f"<ContactoDeudor(tipo={self.tipo}, valor='{self.valor}')>"

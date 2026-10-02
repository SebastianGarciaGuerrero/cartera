"""
Modelos para 'terceros': personas ligadas a una deuda que no son el deudor.

Ejemplos: el aval o codeudor de un crédito, el paciente de una cuenta
médica (cuando quien firmó el pagaré es el padre), el representante legal
de una empresa deudora. Una cobranza puede tener varios terceros, cada uno
con su rol (tabla 'cobranza_terceros'). Importan en lo judicial: al aval
también se le demanda.
"""

from sqlalchemy import Column, String, Text, Date, Boolean, TIMESTAMP, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base
from app.tenancy import TenantMixin


ROLES_TERCERO = ("paciente", "aval", "codeudor", "beneficiario", "representante_legal", "otro")


class Tercero(TenantMixin, Base):
    __tablename__ = "terceros"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    rut = Column(String(12))  # opcional; único por organización si viene
    nombre = Column(String(200), nullable=False)
    fecha_nacimiento = Column(Date)
    direccion = Column(Text)
    departamento = Column(String(50))
    comuna = Column(String(100))
    ciudad = Column(String(100))
    region = Column(String(100))
    observaciones = Column(Text)
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))
    updated_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))

    contactos = relationship(
        "ContactoTercero", back_populates="tercero", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Tercero(rut={self.rut}, nombre='{self.nombre}')>"


class ContactoTercero(TenantMixin, Base):
    __tablename__ = "contactos_tercero"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tercero_id = Column(UUID(as_uuid=True), ForeignKey("terceros.id", ondelete="CASCADE"), nullable=False)
    tipo = Column(String(20), nullable=False)
    valor = Column(String(200), nullable=False)
    activo = Column(Boolean, server_default=text("true"))
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))

    tercero = relationship("Tercero", back_populates="contactos")


class CobranzaTercero(TenantMixin, Base):
    """Vínculo cobranza ↔ tercero con el rol que cumple en esa deuda."""

    __tablename__ = "cobranza_terceros"

    cobranza_id = Column(UUID(as_uuid=True), ForeignKey("cobranzas.id"), primary_key=True)
    tercero_id = Column(UUID(as_uuid=True), ForeignKey("terceros.id"), primary_key=True)
    rol = Column(String(30), primary_key=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))

    cobranza = relationship("Cobranza", back_populates="terceros")
    tercero = relationship("Tercero", lazy="joined")

    @property
    def nombre(self) -> str:
        return self.tercero.nombre if self.tercero else ""

    @property
    def rut(self):
        return self.tercero.rut if self.tercero else None

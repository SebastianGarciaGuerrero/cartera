"""
Modelos de la agenda: recordatorios que cada persona se anota e
indicadores económicos (UF) por fecha.
"""

from sqlalchemy import Column, String, Text, Date, Time, Numeric, TIMESTAMP, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base
from app.tenancy import TenantMixin


class Recordatorio(TenantMixin, Base):
    """
    "Llamar a don Pedro el jueves", "revisar si llegó la transferencia".
    No se borra: se marca hecho o descartado (queda el historial).
    """

    __tablename__ = "recordatorios"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    usuario_id = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"), nullable=False)
    cobranza_id = Column(UUID(as_uuid=True), ForeignKey("cobranzas.id"))
    fecha = Column(Date, nullable=False)
    hora = Column(Time)
    titulo = Column(String(200), nullable=False)
    nota = Column(Text)
    estado = Column(String(20), nullable=False, server_default=text("'pendiente'"))
    completado_at = Column(TIMESTAMP(timezone=True))
    creado_por = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))
    updated_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))

    cobranza = relationship("Cobranza")


class Indicador(Base):
    """Valor de la UF (u otro indicador) en una fecha. Común a todos."""

    __tablename__ = "indicadores"

    codigo = Column(String(20), primary_key=True)
    fecha = Column(Date, primary_key=True)
    valor = Column(Numeric(14, 4), nullable=False)
    fuente = Column(String(50))
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))

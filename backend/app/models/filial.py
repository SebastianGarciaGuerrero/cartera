"""
Modelo SQLAlchemy para la tabla 'filiales'.
Representa las sucursales de un cliente.
Ej: un cliente con sucursales en Iquique, Valparaíso, Temuco.
"""

from sqlalchemy import Column, Integer, String, Boolean, TIMESTAMP, ForeignKey, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base
from app.tenancy import TenantMixin


class Filial(TenantMixin, Base):
    __tablename__ = "filiales"
    
    # ID entero autoincremental (más liviano que UUID para tablas chicas)
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # ForeignKey: este campo apunta a clientes.id
    # PostgreSQL valida que el cliente_id exista antes de aceptar el INSERT
    cliente_id = Column(UUID(as_uuid=True), ForeignKey("clientes.id"), nullable=False)
    
    nombre = Column(String(100), nullable=False)
    activo = Column(Boolean, server_default=text("true"))
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))
    
    # Restricción: no puede haber dos filiales con el mismo nombre
    # dentro del mismo cliente: nadie puede tener dos filiales "Iquique".
    __table_args__ = (
        UniqueConstraint('cliente_id', 'nombre', name='uq_filial_cliente_nombre'),
    )
    
    # Relationship: define cómo navegar desde Filial hacia Cliente.
    # No es una columna real, solo facilita el código Python.
    # filial.cliente te devuelve el objeto Cliente automáticamente.
    cliente = relationship("Cliente", backref="filiales")
    
    def __repr__(self):
        return f"<Filial(id={self.id}, nombre='{self.nombre}')>"
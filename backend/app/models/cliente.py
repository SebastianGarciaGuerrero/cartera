"""
Modelo SQLAlchemy para la tabla 'clientes'.
Representa las empresas mandantes que entregan su cartera para cobrar
(clínicas, retail, servicios: cualquier empresa con cartera morosa).
"""

from sqlalchemy import Column, String, Boolean, Integer, Numeric, Text, TIMESTAMP, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base
from app.tenancy import TenantMixin


class Cliente(TenantMixin, Base):
    """
    Mapea la tabla 'clientes' de PostgreSQL a una clase Python.
    Cada instancia de Cliente representa una fila de la tabla.
    """
    
    # Nombre de la tabla en PostgreSQL
    __tablename__ = "clientes"
    
    # Cada Column representa una columna de la tabla.
    # PostgreSQL genera el UUID automáticamente con gen_random_uuid()
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()")
    )
    
    rut = Column(String(12), nullable=False)  # único por organización
    razon_social = Column(String(200), nullable=False)
    nombre_fantasia = Column(String(200))
    direccion = Column(Text)
    comuna = Column(String(100))
    ciudad = Column(String(100))
    telefono = Column(String(50))
    email = Column(String(150))
    # Datos de transferencia propios (si el deudor le paga directo al
    # mandante). Si está vacío se usan los del estudio.
    instrucciones_pago = Column(Text)
    # A los cuántos días desde el ingreso se sugiere preparar la demanda
    # (NULL = sin sugerencia, 0 = de inmediato).
    dias_para_demanda = Column(Integer)
    # % de honorarios judiciales que fijó el cliente (NULL = libre: se usa el
    # general del estudio y se puede cambiar en cada abono).
    pct_honorarios_judicial = Column(Numeric(5, 2))
    activo = Column(Boolean, server_default=text("true"))
    
    # Timestamps gestionados por PostgreSQL
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))
    updated_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))
    
    # Relación: un cliente tiene muchas filiales.
    # Lazy="select" significa: cargar filiales solo cuando se acceda a ellas.
    # back_populates conecta esto con la propiedad 'cliente' del modelo Filial.
    # (lo definiremos después cuando creemos Filial)
    # filiales = relationship("Filial", back_populates="cliente")
    
    def __repr__(self):
        """Cómo se ve el objeto al imprimirlo (útil para debugging)."""
        return f"<Cliente(rut={self.rut}, razon_social='{self.razon_social}')>"
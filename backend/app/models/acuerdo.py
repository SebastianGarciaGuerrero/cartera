"""
Modelos SQLAlchemy para 'acuerdos_pago' y 'cuotas'.

Un acuerdo formaliza cómo el deudor pagará una cobranza (pie + N cuotas).
- Una cobranza puede tener varios acuerdos en el tiempo (renegociaciones),
  pero solo UNO puede estar 'vigente' a la vez (se valida en el router).
- Las cuotas se generan AUTOMÁTICAMENTE al crear el acuerdo.
- Los montos y las cuotas son inmutables: una renegociación cambia el estado
  del acuerdo a 'renegociado' y crea uno nuevo. Lo único que se edita del
  acuerdo es su estado y la firma del cliente.
"""

from sqlalchemy import (
    Column, String, Text, Integer, Numeric, Date, TIMESTAMP,
    ForeignKey, UniqueConstraint, text
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base
from app.tenancy import TenantMixin


class AcuerdoPago(TenantMixin, Base):
    __tablename__ = "acuerdos_pago"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()")
    )
    cobranza_id = Column(UUID(as_uuid=True), ForeignKey("cobranzas.id"), nullable=False)

    # Fechas
    fecha_acuerdo = Column(Date, nullable=False, server_default=text("CURRENT_DATE"))
    fecha_termino = Column(Date)  # se calcula al crear (vencimiento de la última cuota)

    # Montos del acuerdo
    pie = Column(Numeric(15, 2), server_default=text("0"))  # pago inicial antes de cuotas
    monto_total_acordado = Column(Numeric(15, 2), nullable=False)
    numero_cuotas = Column(Integer, nullable=False, server_default=text("1"))
    dia_pago = Column(Integer)  # día del mes en que se paga (1-31)
    fecha_primera_cuota = Column(Date, nullable=False)

    # Desglose (para el cuadro de rendición al cliente)
    capital = Column(Numeric(15, 2), server_default=text("0"))
    honorarios = Column(Numeric(15, 2), server_default=text("0"))
    intereses = Column(Numeric(15, 2), server_default=text("0"))
    gastos_judiciales = Column(Numeric(15, 2), server_default=text("0"))

    # Estado y tipo
    estado = Column(String(20), nullable=False, server_default=text("'vigente'"))
    tipo_pago = Column(String(20), server_default=text("'extrajudicial'"))

    # Firma del cliente (el mandante debe aprobar el acuerdo)
    firma_cliente = Column(String(30), server_default=text("'sin_firmar'"))
    fecha_firma = Column(Date)

    usuario_id = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"), nullable=False)
    observaciones = Column(Text)
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))
    # Sin updated_at por diseño.

    # Relaciones
    cobranza = relationship("Cobranza", backref="acuerdos")
    # cascade delete-orphan calza con ON DELETE CASCADE de cuotas en la DB.
    cuotas = relationship(
        "Cuota",
        back_populates="acuerdo",
        cascade="all, delete-orphan",
        order_by="Cuota.numero_cuota"
    )

    def __repr__(self):
        return f"<AcuerdoPago(cobranza_id={self.cobranza_id}, estado='{self.estado}')>"


class Cuota(TenantMixin, Base):
    __tablename__ = "cuotas"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()")
    )
    acuerdo_id = Column(
        UUID(as_uuid=True),
        ForeignKey("acuerdos_pago.id", ondelete="CASCADE"),
        nullable=False
    )
    numero_cuota = Column(Integer, nullable=False)  # 1, 2, 3...
    monto = Column(Numeric(15, 2), nullable=False)
    fecha_vencimiento = Column(Date, nullable=False)
    monto_pagado = Column(Numeric(15, 2), nullable=False, server_default=text("0"))
    estado = Column(String(20), nullable=False, server_default=text("'pendiente'"))

    __table_args__ = (
        UniqueConstraint("acuerdo_id", "numero_cuota", name="uq_cuota_acuerdo_numero"),
    )

    acuerdo = relationship("AcuerdoPago", back_populates="cuotas")

    def __repr__(self):
        return f"<Cuota(numero={self.numero_cuota}, monto={self.monto}, estado='{self.estado}')>"

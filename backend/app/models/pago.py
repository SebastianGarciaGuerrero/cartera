"""
Modelo SQLAlchemy para 'pagos'.

Cada pago real recibido. Es la fuente del recupero mensual y del cuadro de
rendición al cliente.

INMUTABLE (igual que gestiones): sin updated_at, sin PUT ni DELETE. Un error
se corrige registrando un pago correctivo, no editando el original.

La lógica de cascada (descontar saldo, actualizar cuota, cerrar acuerdo y
cobranza) vive en el router, dentro de una única transacción.
"""

from sqlalchemy import (
    Column, String, Text, Numeric, Date, TIMESTAMP, ForeignKey, text
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base
from app.tenancy import TenantMixin


class Pago(TenantMixin, Base):
    __tablename__ = "pagos"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()")
    )
    cobranza_id = Column(UUID(as_uuid=True), ForeignKey("cobranzas.id"), nullable=False)
    # cuota_id es opcional: NULL si es un pago directo sin acuerdo formal.
    cuota_id = Column(UUID(as_uuid=True), ForeignKey("cuotas.id"))

    fecha_pago = Column(Date, nullable=False, server_default=text("CURRENT_DATE"))
    monto = Column(Numeric(15, 2), nullable=False)

    # Desglose para el cuadro de rendición. El CAPITAL es la guía: es lo
    # único que descuenta el saldo de la cobranza (honorarios/interés varían
    # según el abono y la UF del día, el capital siempre es fijo).
    capital = Column(Numeric(15, 2), server_default=text("0"))
    honorarios = Column(Numeric(15, 2), server_default=text("0"))
    intereses = Column(Numeric(15, 2), server_default=text("0"))
    gastos_judiciales = Column(Numeric(15, 2), server_default=text("0"))

    forma_pago = Column(String(30))
    numero_comprobante = Column(String(100))
    estado_pago = Column(String(20), nullable=False, server_default=text("'pagado'"))
    descripcion_estado = Column(Text)

    usuario_id = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"), nullable=False)
    observaciones = Column(Text)
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))
    # Sin updated_at → INMUTABLE.

    # Navegación. backref crea cobranza.pagos y cuota.pagos.
    cobranza = relationship("Cobranza", backref="pagos")
    cuota = relationship("Cuota", backref="pagos")

    def __repr__(self):
        return f"<Pago(cobranza_id={self.cobranza_id}, monto={self.monto})>"

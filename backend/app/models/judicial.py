"""
Modelo SQLAlchemy para 'gestiones_judiciales'.

Información adicional cuando la cobranza pasa a tribunal: rol de la causa,
tribunal, abogado a cargo y estado del proceso.

Relación 1-a-1 con cobranzas (UNIQUE en cobranza_id): una cobranza tiene a
lo más UNA ficha judicial. A diferencia de las gestiones normales, esta ficha
SÍ es editable (tiene updated_at): el estado del proceso avanza en el tiempo.
"""

from sqlalchemy import Column, String, Text, Date, TIMESTAMP, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base
from app.tenancy import TenantMixin


class GestionJudicial(TenantMixin, Base):
    __tablename__ = "gestiones_judiciales"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()")
    )
    # UNIQUE: una sola ficha judicial por cobranza.
    cobranza_id = Column(
        UUID(as_uuid=True),
        ForeignKey("cobranzas.id"),
        nullable=False,
        unique=True,
    )

    numero_rol = Column(String(50))       # rol de la causa (ej. C-1234-2026)
    tribunal = Column(String(200))        # ej. 2° Juzgado Civil de Valparaíso
    fecha_ingreso = Column(Date)          # cuándo ingresó la demanda
    estado_proceso = Column(String(100))  # texto libre: notificación, embargo...
    abogado_id = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"))

    observaciones = Column(Text)
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))
    updated_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))

    # cobranza.judicial devuelve la ficha (o None si no ha ido a tribunal).
    cobranza = relationship("Cobranza", backref="judicial")

    def __repr__(self):
        return f"<GestionJudicial(rol={self.numero_rol}, tribunal='{self.tribunal}')>"

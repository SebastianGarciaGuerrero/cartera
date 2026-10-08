"""
Enlace personal del deudor (portal del deudor).

El estudio lo genera desde la ficha y se lo manda al deudor por WhatsApp o
correo. Se guarda solo el hash del token; para abrirlo el deudor además
escribe su RUT. Un deudor tiene a lo más un enlace vigente: generar otro
revoca el anterior.
"""

from sqlalchemy import Column, String, Integer, TIMESTAMP, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base
from app.tenancy import TenantMixin


class EnlaceDeudor(TenantMixin, Base):
    __tablename__ = "enlaces_deudor"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    deudor_id = Column(UUID(as_uuid=True), ForeignKey("deudores.id"), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    creado_por = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))
    expira_at = Column(TIMESTAMP(timezone=True), nullable=False)
    revocado_at = Column(TIMESTAMP(timezone=True))
    bloqueado_at = Column(TIMESTAMP(timezone=True))
    intentos_fallidos = Column(Integer, nullable=False, server_default=text("0"))
    accesos = Column(Integer, nullable=False, server_default=text("0"))
    ultimo_acceso_at = Column(TIMESTAMP(timezone=True))

    deudor = relationship("Deudor")

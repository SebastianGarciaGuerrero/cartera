"""
Modelo SQLAlchemy para 'audit_log'.

Registro INMUTABLE de todos los cambios del sistema: quién hizo qué, cuándo,
y el antes/después de cada registro. Solo INSERT (nunca UPDATE ni DELETE).
Cumple la Ley 21.719 de Protección de Datos Personales (Chile).

Las filas las escribe automáticamente app/auditoria.py: ningún router
inserta aquí a mano.
"""

from sqlalchemy import Column, String, Text, TIMESTAMP, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.database import Base
from app.tenancy import TenantMixin


class AuditLog(TenantMixin, Base):
    __tablename__ = "audit_log"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()")
    )
    # Nullable: eventos de plataforma (alta de organizaciones) no pertenecen
    # a ninguna organización; esas filas no las ve ningún estudio.
    organizacion_id = Column(UUID(as_uuid=True), ForeignKey("organizaciones.id"))
    # Nullable: acciones de sistema (seeds, migraciones) no tienen usuario.
    usuario_id = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    accion = Column(String(10), nullable=False)   # INSERT / UPDATE / DELETE
    tabla = Column(String(100), nullable=False)
    registro_id = Column(Text, nullable=False)    # UUID o número del registro
    datos_anteriores = Column(JSONB)              # estado antes del cambio
    datos_nuevos = Column(JSONB)                  # estado después del cambio
    ip_origen = Column(String(45))
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))

    def __repr__(self):
        return f"<AuditLog({self.accion} {self.tabla} {self.registro_id})>"

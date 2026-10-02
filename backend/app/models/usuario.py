"""
Modelo SQLAlchemy para 'usuarios' (las personas que usan la plataforma).

Cada usuario pertenece a UNA organización. El email es único en toda la
plataforma (identifica a la persona en el login).

REGLA: password_hash, el secreto 2FA y los códigos de recuperación NUNCA se
exponen en respuestas API.
"""

from sqlalchemy import Column, String, Text, Boolean, Integer, BigInteger, TIMESTAMP, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.database import Base
from app.tenancy import TenantMixin


class Usuario(TenantMixin, Base):
    __tablename__ = "usuarios"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    nombre = Column(String(100), nullable=False)
    email = Column(String(150), nullable=False)
    password_hash = Column(Text, nullable=False)  # argon2id (o bcrypt heredado)
    rol_id = Column(Integer, ForeignKey("roles.id"), nullable=False)
    # Solo para usuarios del portal de mandantes: la empresa cuya cartera ven.
    cliente_id = Column(UUID(as_uuid=True), ForeignKey("clientes.id"))
    activo = Column(Boolean, server_default=text("true"))
    ultimo_acceso = Column(TIMESTAMP(timezone=True))

    # Seguridad de la cuenta
    mfa_activo = Column(Boolean, nullable=False, server_default=text("false"))
    mfa_secreto_cifrado = Column(Text)
    mfa_ultimo_paso = Column(BigInteger)  # evita reusar el mismo código TOTP
    mfa_codigos_recuperacion = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    intentos_fallidos = Column(Integer, nullable=False, server_default=text("0"))
    bloqueado_hasta = Column(TIMESTAMP(timezone=True))
    password_actualizada_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))
    debe_cambiar_password = Column(Boolean, nullable=False, server_default=text("false"))

    created_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))
    updated_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))

    rol = relationship("Rol", backref="usuarios", lazy="joined")

    @property
    def rol_nombre(self) -> str | None:
        return self.rol.nombre if self.rol else None

    def __repr__(self):
        return f"<Usuario(nombre='{self.nombre}', email='{self.email}')>"

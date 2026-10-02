"""
Modelos de seguridad de cuentas: sesiones, tokens de un solo uso y la
bitácora de accesos.

Sesion y TokenUnUso NO llevan TenantMixin a propósito: solo los toca el
código de autenticación, que corre en modo sistema (antes de saber la
organización). El rol de la app (cartera_app) no tiene acceso a esas tablas.
"""

from sqlalchemy import Column, String, Boolean, TIMESTAMP, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.database import Base
from app.tenancy import TenantMixin


class Sesion(Base):
    """Un inicio de sesión. Guarda solo el HASH del refresh token."""

    __tablename__ = "sesiones"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    usuario_id = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"), nullable=False)
    organizacion_id = Column(UUID(as_uuid=True), ForeignKey("organizaciones.id"), nullable=False)
    refresh_hash = Column(String(64), nullable=False, unique=True)
    # Hash del refresh anterior (rotado): si alguien lo vuelve a presentar,
    # es señal de robo y se revoca la sesión completa.
    refresh_anterior_hash = Column(String(64))
    creada_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()"))
    ultimo_uso_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()"))
    expira_at = Column(TIMESTAMP(timezone=True), nullable=False)
    revocada_at = Column(TIMESTAMP(timezone=True))
    motivo_revocacion = Column(String(40))
    ip = Column(String(45))
    user_agent = Column(String(300))


class TokenUnUso(Base):
    """Enlace de recuperación de contraseña o invitación (solo el hash)."""

    __tablename__ = "tokens_un_uso"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    usuario_id = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"), nullable=False)
    proposito = Column(String(20), nullable=False)  # reset_password / invitacion
    token_hash = Column(String(64), nullable=False, unique=True)
    expira_at = Column(TIMESTAMP(timezone=True), nullable=False)
    usado_at = Column(TIMESTAMP(timezone=True))
    ip = Column(String(45))
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))


class EventoAcceso(TenantMixin, Base):
    """Bitácora inmutable de accesos (login, fallos, bloqueos, 2FA...)."""

    __tablename__ = "eventos_acceso"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    # Nullable: un intento con un email que no existe no tiene organización.
    organizacion_id = Column(UUID(as_uuid=True), ForeignKey("organizaciones.id"))
    usuario_id = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    email = Column(String(150))
    evento = Column(String(40), nullable=False)
    exito = Column(Boolean, nullable=False)
    ip = Column(String(45))
    user_agent = Column(String(300))
    detalle = Column(JSONB)
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))

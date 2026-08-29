"""
Modelo SQLAlchemy para 'usuarios' (las personas del equipo de cobranza).

Todavía no tiene router/schema propios (eso llega con la autenticación JWT),
pero el modelo se define ahora para que las FK de otras tablas
(cobranzas.ejecutivo_id, gestiones.usuario_id, acuerdos.usuario_id) puedan
resolver su tabla destino.

REGLA: password_hash NUNCA se expone en respuestas API.
"""

from sqlalchemy import Column, String, Boolean, Integer, TIMESTAMP, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()")
    )
    nombre = Column(String(100), nullable=False)
    email = Column(String(150), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)  # bcrypt, nunca texto plano
    rol_id = Column(Integer, ForeignKey("roles.id"), nullable=False)
    activo = Column(Boolean, server_default=text("true"))
    ultimo_acceso = Column(TIMESTAMP(timezone=True))
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))
    updated_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))

    rol = relationship("Rol", backref="usuarios")

    def __repr__(self):
        return f"<Usuario(nombre='{self.nombre}', email='{self.email}')>"

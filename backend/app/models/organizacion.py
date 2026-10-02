"""
Modelo 'organizaciones': cada estudio o empresa de cobranza que usa la
plataforma (el tenant del SaaS).

Todo dato de negocio cuelga de una organización. El plan define qué módulos
tiene habilitados (ver app/planes.py) y `configuracion` guarda lo que cada
estudio ajusta por su cuenta (etiquetas de la interfaz, preferencias).
"""

from sqlalchemy import Column, String, Integer, Date, TIMESTAMP, text
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.database import Base


class Organizacion(Base):
    __tablename__ = "organizaciones"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    nombre = Column(String(200), nullable=False)
    slug = Column(String(60), nullable=False, unique=True)
    plan = Column(String(20), nullable=False, server_default=text("'base'"))
    estado = Column(String(20), nullable=False, server_default=text("'activa'"))
    prueba_hasta = Column(Date)
    numero_cobranza_siguiente = Column(Integer, nullable=False, server_default=text("1000"))
    configuracion = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))
    updated_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))

    @property
    def habilitada(self) -> bool:
        return self.estado in ("prueba", "activa")

    def __repr__(self):
        return f"<Organizacion(slug='{self.slug}', plan='{self.plan}')>"

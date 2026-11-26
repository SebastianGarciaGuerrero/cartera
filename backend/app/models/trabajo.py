"""
Trabajos en segundo plano (cargas masivas grandes): avance y resultado.

La carga corre en un hilo aparte; la pantalla consulta el avance cada pocos
segundos. Si el servidor se reinicia a mitad de camino, el trabajo queda
"procesando" y se marca como error al consultarlo (ver routers/trabajos.py).
"""

from sqlalchemy import Column, String, Integer, TIMESTAMP, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.database import Base
from app.tenancy import TenantMixin


class Trabajo(TenantMixin, Base):
    __tablename__ = "trabajos"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tipo = Column(String(40), nullable=False)
    estado = Column(String(20), nullable=False, server_default=text("'en_cola'"))
    archivo = Column(String(255))
    total = Column(Integer, nullable=False, server_default=text("0"))
    procesadas = Column(Integer, nullable=False, server_default=text("0"))
    resultado = Column(JSONB)
    creado_por = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))
    terminado_at = Column(TIMESTAMP(timezone=True))

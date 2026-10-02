"""
Campos personalizados: cada organización agrega sus propios datos a las
cobranzas y deudores sin tocar código ni base de datos.

Ejemplos: "Previsión" para una clínica, "Patente" para una automotora,
"N° de contrato" para una inmobiliaria. Se pueden limitar a un mandante
(cliente_id): el campo solo aparece en las cobranzas de ese cliente.

Los valores se guardan en `datos_extra` (JSONB) de la cobranza o del deudor,
con `clave` como llave. La validación vive en app/campos.py.
"""

from sqlalchemy import Column, String, Boolean, Integer, TIMESTAMP, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.database import Base
from app.tenancy import TenantMixin

TIPOS_CAMPO = ("texto", "numero", "monto", "fecha", "seleccion", "si_no")
ENTIDADES_CAMPO = ("cobranza", "deudor")


class CampoPersonalizado(TenantMixin, Base):
    __tablename__ = "campos_personalizados"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    entidad = Column(String(20), nullable=False)        # cobranza / deudor
    clave = Column(String(50), nullable=False)          # llave en datos_extra
    etiqueta = Column(String(100), nullable=False)      # lo que ve el usuario
    tipo = Column(String(20), nullable=False, server_default=text("'texto'"))
    opciones = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    cliente_id = Column(UUID(as_uuid=True), ForeignKey("clientes.id"))
    obligatorio = Column(Boolean, nullable=False, server_default=text("false"))
    orden = Column(Integer, nullable=False, server_default=text("0"))
    activo = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))
    updated_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))

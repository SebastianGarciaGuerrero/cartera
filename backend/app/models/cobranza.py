"""
Modelo SQLAlchemy para la tabla 'cobranzas'.

*** El núcleo del sistema. Una cobranza = una deuda concreta. ***

Conecta cliente (el mandante) + filial (sucursal) + deudor (a quien se le
cobra) + terceros opcionales (aval, codeudor, paciente...).

IDENTIFICADORES:
  numero     → N° de cobranza. Correlativo POR ORGANIZACIÓN que asigna
               PostgreSQL (trigger); nunca cambia. Se puede indicar a mano al
               migrar la cartera de un sistema anterior.
  id_externo → ID de la cobranza en el sistema del cliente. ÚNICO POR CLIENTE.

Lo propio de cada rubro (previsión de salud, N° de patente, etc.) no va en
columnas fijas: va en `datos_extra`, según los campos personalizados que
defina cada organización (ver models/campo_personalizado.py).
"""

from sqlalchemy import (
    Column, String, Boolean, Text, Date, Integer, Numeric,
    TIMESTAMP, ForeignKey, UniqueConstraint, FetchedValue, text
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.database import Base
from app.tenancy import TenantMixin


class Cobranza(TenantMixin, Base):
    __tablename__ = "cobranzas"

    # --- Identificadores ---
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    # Lo asigna el trigger trg_cobranzas_numero si viene NULL.
    numero = Column(Integer, FetchedValue(), nullable=False)

    # --- Vínculos principales ---
    cliente_id = Column(UUID(as_uuid=True), ForeignKey("clientes.id"), nullable=False)
    filial_id = Column(Integer, ForeignKey("filiales.id"))
    deudor_id = Column(UUID(as_uuid=True), ForeignKey("deudores.id"), nullable=False)

    # --- Identificadores externos ---
    id_externo = Column(String(50))
    numero_operacion = Column(String(50))  # N° de operación/liquidación del cliente

    # --- Montos (NUMERIC, nunca FLOAT para dinero) ---
    monto_original = Column(Numeric(15, 2), nullable=False)
    monto_actual = Column(Numeric(15, 2), nullable=False)
    capital = Column(Numeric(15, 2))
    intereses = Column(Numeric(15, 2), server_default=text("0"))
    honorarios = Column(Numeric(15, 2), server_default=text("0"))
    gastos = Column(Numeric(15, 2), server_default=text("0"))

    # --- Fechas ---
    fecha_origen = Column(Date)  # operación/prestación que originó la deuda
    fecha_ingreso = Column(Date, nullable=False, server_default=text("CURRENT_DATE"))
    fecha_traspaso = Column(Date)  # cuando el cliente la derivó a judicial

    # --- Documento que respalda la deuda (pagaré, factura, letra...) ---
    tipo_documento = Column(String(30), server_default=text("'pagare'"))
    numero_documento = Column(String(50))
    fecha_emision_documento = Column(Date)
    fecha_vencimiento_documento = Column(Date)  # base para la prescripción
    comprobante_envio = Column(String(200))
    autorizacion_firma = Column(Boolean, server_default=text("false"))
    fecha_envio_documentos = Column(Date)

    # --- Estado y tipo ---
    estado = Column(String(20), nullable=False, server_default=text("'activa'"))
    tipo = Column(String(20), nullable=False, server_default=text("'extrajudicial'"))
    etapa_cobranza = Column(String(50))

    # --- Ejecutivo responsable ---
    ejecutivo_id = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"))

    # --- Campos personalizados de la organización ---
    datos_extra = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    observaciones = Column(Text)
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))
    updated_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))

    __table_args__ = (
        UniqueConstraint("cliente_id", "id_externo", name="uq_cobranza_id_externo"),
    )
    # Trae el N° asignado por el trigger en el mismo INSERT (RETURNING).
    __mapper_args__ = {"eager_defaults": True}

    cliente = relationship("Cliente", backref="cobranzas")
    filial = relationship("Filial", backref="cobranzas")
    deudor = relationship("Deudor", backref="cobranzas")
    terceros = relationship(
        "CobranzaTercero", back_populates="cobranza", cascade="all, delete-orphan"
    )

    # Para listados (se cargan con joinedload en los routers).
    @property
    def deudor_nombre(self):
        return self.deudor.nombre if self.deudor else None

    @property
    def deudor_rut(self):
        return self.deudor.rut if self.deudor else None

    @property
    def cliente_nombre(self):
        return (self.cliente.nombre_fantasia or self.cliente.razon_social) if self.cliente else None

    def __repr__(self):
        return f"<Cobranza(numero={self.numero}, estado='{self.estado}')>"

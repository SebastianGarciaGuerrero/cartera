"""
Modelo SQLAlchemy para la tabla 'cobranzas'.

*** El núcleo del sistema. Una cobranza = una deuda concreta. ***

Conecta cliente (el mandante) + filial (sucursal) + deudor (quien firmó el
pagaré) + opcionalmente paciente (quien recibió la atención).

IDENTIFICADORES:
  numero     → N° de cobranza. ÚNICO GLOBAL. Lo genera PostgreSQL (IDENTITY),
               NUNCA se inserta a mano ni cambia.
  id_externo → ID de la cobranza en el sistema del cliente. ÚNICO POR CLIENTE.

Un mismo deudor puede tener N cobranzas (deudas distintas).
"""

from sqlalchemy import (
    Column, String, Boolean, Text, Date, Integer, Numeric,
    TIMESTAMP, ForeignKey, UniqueConstraint, Identity, text
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class Cobranza(Base):
    __tablename__ = "cobranzas"

    # --- Identificadores ---
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()")
    )
    # numero lo genera PostgreSQL (GENERATED ALWAYS AS IDENTITY).
    # Identity(always=True) le dice a SQLAlchemy que NO lo incluya en el
    # INSERT (sin esto, Postgres rechaza el insert con GeneratedAlways).
    numero = Column(Integer, Identity(always=True), nullable=False, unique=True)

    # --- Vínculos principales ---
    cliente_id = Column(UUID(as_uuid=True), ForeignKey("clientes.id"), nullable=False)
    filial_id = Column(Integer, ForeignKey("filiales.id"))
    deudor_id = Column(UUID(as_uuid=True), ForeignKey("deudores.id"), nullable=False)
    # paciente_id es opcional: NULL cuando deudor y paciente son la misma persona.
    paciente_id = Column(UUID(as_uuid=True), ForeignKey("pacientes.id"))

    # --- Identificadores externos ---
    id_externo = Column(String(50))
    numero_liquidacion = Column(String(50))

    # --- Montos (NUMERIC, nunca FLOAT para dinero) ---
    monto_original = Column(Numeric(15, 2), nullable=False)
    monto_actual = Column(Numeric(15, 2), nullable=False)
    capital = Column(Numeric(15, 2))
    intereses = Column(Numeric(15, 2), server_default=text("0"))
    honorarios = Column(Numeric(15, 2), server_default=text("0"))
    gastos = Column(Numeric(15, 2), server_default=text("0"))

    # --- Fechas de la atención médica ---
    fecha_atencion = Column(Date)
    fecha_alta = Column(Date)
    prevision = Column(String(80))

    # --- Fechas operacionales ---
    fecha_ingreso = Column(Date, nullable=False, server_default=text("CURRENT_DATE"))
    fecha_traspaso = Column(Date)

    # --- Documento que identifica la deuda (pagaré, factura, letra...) ---
    tipo_documento = Column(String(30), server_default=text("'pagare'"))
    numero_pagare = Column(String(50))  # N° del documento
    fecha_ejecucion_pagare = Column(Date)
    fecha_vencimiento_pagare = Column(Date)
    comprobante_envio = Column(String(200))
    autorizacion_firma = Column(Boolean, server_default=text("false"))
    fecha_envio_documentos = Column(Date)

    # --- Estado y tipo ---
    estado = Column(String(20), nullable=False, server_default=text("'activa'"))
    tipo = Column(String(20), nullable=False, server_default=text("'extrajudicial'"))
    etapa_cobranza = Column(String(50))

    # --- Ejecutivo responsable ---
    ejecutivo_id = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"))

    observaciones = Column(Text)
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))
    updated_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))

    # Restricción clave: id_externo único por cliente.
    __table_args__ = (
        UniqueConstraint("cliente_id", "id_externo", name="uq_cobranza_id_externo"),
    )

    # Relaciones para navegar y armar la ficha de detalle.
    # (paciente y ejecutivo aún no tienen modelo propio; se agregarán
    #  cuando se construyan esos módulos.)
    cliente = relationship("Cliente", backref="cobranzas")
    filial = relationship("Filial", backref="cobranzas")
    deudor = relationship("Deudor", backref="cobranzas")

    def __repr__(self):
        return f"<Cobranza(numero={self.numero}, estado='{self.estado}')>"

"""
Modelos del módulo judicial (migración 0010).

  Tribunal, TipoTramite  → catálogos mixtos (sistema + propios).
  Causa                  → una demanda: un rol en un tribunal. Puede llevar
                           varias cobranzas del mismo deudor y cliente.
  Tramite                → lo que pasa en la causa. INMUTABLE (sin
                           updated_at), igual que las gestiones.
  Embargo                → bien trabado y su estado; se edita a medida que
                           avanza (trabado → retirado → rematado).
  Gasto, RendicionGastos → lo que paga el estudio y después le cobra al
                           mandante.
  CambioEtapa            → historial del ciclo de vida de la cobranza (lo
                           escribe un trigger, ver app/ciclo.py).
"""

from sqlalchemy import (
    Boolean, Column, Date, ForeignKey, Integer, Numeric, String, Text, TIMESTAMP, text
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base
from app.tenancy import TenantGlobalMixin, TenantMixin


def _uuid_pk():
    return Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))


class Tribunal(TenantGlobalMixin, Base):
    __tablename__ = "tribunales"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nombre = Column(String(150), nullable=False)
    ciudad = Column(String(80))
    competencia = Column(String(20), nullable=False, server_default=text("'civil'"))
    activo = Column(Boolean, nullable=False, server_default=text("true"))

    @property
    def propio(self) -> bool:
        return self.organizacion_id is not None


class TipoTramite(TenantGlobalMixin, Base):
    __tablename__ = "tipos_tramite"

    id = Column(Integer, primary_key=True, autoincrement=True)
    codigo = Column(String(40))
    nombre = Column(String(150), nullable=False)
    etapa = Column(String(20))  # demanda / notificacion / embargo / defensa / remate
    plazo_dias = Column(Integer)  # revisar en N días corridos
    siguiente_id = Column(Integer, ForeignKey("tipos_tramite.id"))
    genera_gasto = Column(Boolean, nullable=False, server_default=text("false"))
    alerta = Column(Boolean, nullable=False, server_default=text("false"))
    nota = Column(String(300))
    resultado = Column(String(30))  # si normalmente cierra la causa
    orden = Column(Integer, nullable=False, server_default=text("0"))
    activo = Column(Boolean, nullable=False, server_default=text("true"))

    @property
    def propio(self) -> bool:
        return self.organizacion_id is not None


class Causa(TenantMixin, Base):
    __tablename__ = "causas"

    id = _uuid_pk()
    cliente_id = Column(UUID(as_uuid=True), ForeignKey("clientes.id"), nullable=False)
    deudor_id = Column(UUID(as_uuid=True), ForeignKey("deudores.id"), nullable=False)
    rol = Column(String(40))
    tribunal_id = Column(Integer, ForeignKey("tribunales.id"))
    procedimiento = Column(String(30), nullable=False, server_default=text("'ejecutivo'"))
    etapa_procesal = Column(String(20), nullable=False, server_default=text("'demanda'"))
    estado = Column(String(20), nullable=False, server_default=text("'vigente'"))
    resultado = Column(String(30))
    fecha_ingreso = Column(Date, nullable=False)
    fecha_termino = Column(Date)
    cuantia = Column(Numeric(15, 2))
    caratula = Column(String(250))
    abogado_id = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    procurador_id = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    observaciones = Column(Text)
    creado_por = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))
    updated_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))

    cliente = relationship("Cliente")
    deudor = relationship("Deudor")
    tribunal = relationship("Tribunal")
    abogado = relationship("Usuario", foreign_keys=[abogado_id])
    procurador = relationship("Usuario", foreign_keys=[procurador_id])
    vinculos = relationship("CausaCobranza", back_populates="causa", cascade="all")


class CausaCobranza(TenantMixin, Base):
    __tablename__ = "causa_cobranzas"

    causa_id = Column(UUID(as_uuid=True), ForeignKey("causas.id"), primary_key=True)
    cobranza_id = Column(UUID(as_uuid=True), ForeignKey("cobranzas.id"), primary_key=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))

    causa = relationship("Causa", back_populates="vinculos")
    cobranza = relationship("Cobranza")


class Tramite(TenantMixin, Base):
    __tablename__ = "tramites"

    id = _uuid_pk()
    causa_id = Column(UUID(as_uuid=True), ForeignKey("causas.id"), nullable=False)
    tipo_id = Column(Integer, ForeignKey("tipos_tramite.id"))  # NULL = observación
    fecha = Column(Date, nullable=False)
    descripcion = Column(Text)
    plazo_fecha = Column(Date)
    siguiente_id = Column(Integer, ForeignKey("tipos_tramite.id"))
    usuario_id = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))
    # Sin updated_at → INMUTABLE.

    tipo = relationship("TipoTramite", foreign_keys=[tipo_id])
    siguiente = relationship("TipoTramite", foreign_keys=[siguiente_id])
    usuario = relationship("Usuario")

    @property
    def tipo_nombre(self):
        return self.tipo.nombre if self.tipo else None

    @property
    def siguiente_nombre(self):
        return self.siguiente.nombre if self.siguiente else None

    @property
    def usuario_nombre(self):
        return self.usuario.nombre if self.usuario else None


class Embargo(TenantMixin, Base):
    __tablename__ = "embargos"

    id = _uuid_pk()
    causa_id = Column(UUID(as_uuid=True), ForeignKey("causas.id"), nullable=False)
    tipo_bien = Column(String(20), nullable=False)
    descripcion = Column(String(300), nullable=False)
    estado = Column(String(20), nullable=False, server_default=text("'trabado'"))
    fecha_traba = Column(Date)
    inscripcion = Column(String(150))
    depositario = Column(String(150))
    monto_tasacion = Column(Numeric(15, 2))
    fecha_remate = Column(Date)
    monto_remate = Column(Numeric(15, 2))
    observaciones = Column(Text)
    creado_por = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))
    updated_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))


class RendicionGastos(TenantMixin, Base):
    __tablename__ = "rendiciones_gastos"

    id = _uuid_pk()
    numero = Column(Integer, nullable=False)
    cliente_id = Column(UUID(as_uuid=True), ForeignKey("clientes.id"), nullable=False)
    fecha = Column(Date, nullable=False)
    total = Column(Numeric(15, 2), nullable=False)
    estado = Column(String(20), nullable=False, server_default=text("'enviada'"))
    fecha_pago = Column(Date)
    observaciones = Column(Text)
    creado_por = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))
    updated_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))

    cliente = relationship("Cliente")
    gastos = relationship("Gasto", back_populates="rendicion")

    @property
    def cliente_nombre(self):
        return (self.cliente.nombre_fantasia or self.cliente.razon_social) if self.cliente else None


class Gasto(TenantMixin, Base):
    __tablename__ = "gastos"

    id = _uuid_pk()
    cliente_id = Column(UUID(as_uuid=True), ForeignKey("clientes.id"), nullable=False)
    cobranza_id = Column(UUID(as_uuid=True), ForeignKey("cobranzas.id"))
    causa_id = Column(UUID(as_uuid=True), ForeignKey("causas.id"))
    tramite_id = Column(UUID(as_uuid=True), ForeignKey("tramites.id"))
    fecha = Column(Date, nullable=False)
    tipo = Column(String(20), nullable=False, server_default=text("'receptor'"))
    concepto = Column(String(200), nullable=False)
    monto = Column(Numeric(15, 2), nullable=False)
    proveedor = Column(String(150))
    numero_boleta = Column(String(50))
    estado = Column(String(20), nullable=False, server_default=text("'por_rendir'"))
    rendicion_id = Column(UUID(as_uuid=True), ForeignKey("rendiciones_gastos.id"))
    fecha_reembolso = Column(Date)
    observaciones = Column(Text)
    usuario_id = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))
    updated_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))

    cliente = relationship("Cliente")
    cobranza = relationship("Cobranza")
    causa = relationship("Causa")
    rendicion = relationship("RendicionGastos", back_populates="gastos")

    @property
    def cliente_nombre(self):
        return (self.cliente.nombre_fantasia or self.cliente.razon_social) if self.cliente else None

    @property
    def numero_cobranza(self):
        return self.cobranza.numero if self.cobranza else None

    @property
    def rol_causa(self):
        return self.causa.rol if self.causa else None

    @property
    def numero_rendicion(self):
        return self.rendicion.numero if self.rendicion else None


class CambioEtapa(TenantMixin, Base):
    __tablename__ = "cambios_etapa"

    id = _uuid_pk()
    cobranza_id = Column(UUID(as_uuid=True), ForeignKey("cobranzas.id"), nullable=False)
    etapa_anterior = Column(String(20))
    etapa_nueva = Column(String(20), nullable=False)
    usuario_id = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    motivo = Column(String(300))
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))

    usuario = relationship("Usuario")

    @property
    def usuario_nombre(self):
        return self.usuario.nombre if self.usuario else None


class DocumentoCobranza(TenantMixin, Base):
    """Cheque, factura, letra, pagaré… que respalda una cobranza (varios por cobranza)."""

    __tablename__ = "documentos_cobranza"

    id = _uuid_pk()
    cobranza_id = Column(UUID(as_uuid=True), ForeignKey("cobranzas.id"), nullable=False)
    tipo = Column(String(20), nullable=False, server_default=text("'pagare'"))
    numero = Column(String(50))
    fecha_emision = Column(Date)
    fecha_vencimiento = Column(Date)
    monto = Column(Numeric(15, 2))
    banco = Column(String(80))
    plaza = Column(String(80))
    causal_protesto = Column(String(80))
    fecha_protesto = Column(Date)
    observaciones = Column(Text)
    activo = Column(Boolean, nullable=False, server_default=text("true"))
    creado_por = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))
    updated_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))

    @property
    def fecha_prescripcion(self):
        from app.ciclo import prescripcion

        # Cheque: la acción corre desde el protesto; el resto, desde el vencimiento.
        base = self.fecha_protesto if self.tipo == "cheque" and self.fecha_protesto else self.fecha_vencimiento
        return prescripcion(self.tipo, base)

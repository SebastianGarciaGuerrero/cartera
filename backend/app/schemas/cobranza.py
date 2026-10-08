"""
Schemas Pydantic para la entidad Cobranza (el núcleo del sistema).

Reglas reflejadas aquí:
- 'numero' (N° de cobranza) lo asigna PostgreSQL (correlativo por organización):
  nunca se recibe en Create/Update.
- 'cliente_id' y 'deudor_id' se fijan al crear y NO se pueden cambiar después
  (no aparecen en CobranzaUpdate).
- 'monto_actual' arranca igual a 'monto_original' (lo hace el router) y luego
  lo mueven los pagos: no se edita a mano en el alta.
"""

from uuid import UUID
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional, Literal
from pydantic import BaseModel, Field, ConfigDict

from app.schemas.cliente import ClienteResponse
from app.schemas.filial import FilialResponse
from app.schemas.deudor import DeudorResponse


class TerceroEnCobranza(BaseModel):
    """Aval, codeudor, paciente... ligado a la cobranza."""
    tercero_id: UUID
    rol: str
    nombre: str
    rut: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# Estados y tipo como Literal de Pydantic: validan la entrada en la API.
# OJO (decisión 🟢 fácil de cambiar): esta lista debe coincidir con el CHECK
# de la tabla en 001_schema.sql. Agregar/quitar un estado es cambiar esta
# línea + un ALTER TABLE. Si en el futuro cambian mucho, se migra a una tabla
# catálogo 'estados_cobranza'.
EstadoCobranza = Literal[
    "activa", "acuerdo_pago", "judicial", "pagada", "archivada", "castigo"
]
TipoCobranza = Literal["extrajudicial", "judicial"]
TipoDocumento = Literal[
    "pagare", "factura", "letra", "cheque", "contrato", "boleta", "credito", "otro"
]


class CobranzaBase(BaseModel):
    """Campos editables que comparten Create y Update."""
    # Vínculo editable (la filial sí se puede corregir)
    filial_id: Optional[int] = None

    # Identificadores externos
    id_externo: Optional[str] = Field(None, max_length=50)
    numero_operacion: Optional[str] = Field(None, max_length=50)

    # Montos
    monto_original: Decimal = Field(..., ge=0, max_digits=15, decimal_places=2)
    capital: Optional[Decimal] = Field(None, max_digits=15, decimal_places=2)
    intereses: Optional[Decimal] = Field(Decimal("0"), max_digits=15, decimal_places=2)
    honorarios: Optional[Decimal] = Field(Decimal("0"), max_digits=15, decimal_places=2)
    gastos: Optional[Decimal] = Field(Decimal("0"), max_digits=15, decimal_places=2)

    # Fechas
    fecha_origen: Optional[date] = None  # operación que originó la deuda
    fecha_ingreso: Optional[date] = None
    fecha_traspaso: Optional[date] = None

    # Documento que identifica la deuda (pagaré, factura, letra...)
    tipo_documento: TipoDocumento = "pagare"
    numero_documento: Optional[str] = Field(None, max_length=50)
    fecha_emision_documento: Optional[date] = None
    fecha_vencimiento_documento: Optional[date] = None
    comprobante_envio: Optional[str] = Field(None, max_length=200)
    autorizacion_firma: bool = False
    fecha_envio_documentos: Optional[date] = None

    # Estado y tipo
    estado: EstadoCobranza = "activa"
    tipo: TipoCobranza = "extrajudicial"
    etapa_cobranza: Optional[str] = Field(None, max_length=50)

    # Ejecutivo responsable
    ejecutivo_id: Optional[UUID] = None
    observaciones: Optional[str] = None

    # Campos personalizados de la organización (clave → valor)
    datos_extra: dict = Field(default_factory=dict)


class CobranzaCreate(CobranzaBase):
    """
    Datos para crear una cobranza nueva.
    cliente_id y deudor_id son obligatorios y quedan fijos (inmutables).
    'numero' NO se incluye: lo genera PostgreSQL.
    'monto_actual' NO se incluye: el router lo iguala a monto_original.
    """
    cliente_id: UUID
    deudor_id: UUID


class CobranzaUpdate(BaseModel):
    """
    Actualización de una cobranza. Todos los campos opcionales.
    NO incluye numero, cliente_id ni deudor_id: son inmutables.
    El cambio de 'estado' (a pagada, archivada, castigo, etc.) se hace aquí.
    """
    filial_id: Optional[int] = None
    id_externo: Optional[str] = None
    numero_operacion: Optional[str] = None

    monto_original: Optional[Decimal] = Field(None, ge=0, max_digits=15, decimal_places=2)
    monto_actual: Optional[Decimal] = Field(None, ge=0, max_digits=15, decimal_places=2)
    capital: Optional[Decimal] = Field(None, max_digits=15, decimal_places=2)
    intereses: Optional[Decimal] = Field(None, max_digits=15, decimal_places=2)
    honorarios: Optional[Decimal] = Field(None, max_digits=15, decimal_places=2)
    gastos: Optional[Decimal] = Field(None, max_digits=15, decimal_places=2)

    fecha_origen: Optional[date] = None
    fecha_ingreso: Optional[date] = None
    fecha_traspaso: Optional[date] = None

    tipo_documento: Optional[TipoDocumento] = None
    numero_documento: Optional[str] = None
    fecha_emision_documento: Optional[date] = None
    fecha_vencimiento_documento: Optional[date] = None
    comprobante_envio: Optional[str] = None
    autorizacion_firma: Optional[bool] = None
    fecha_envio_documentos: Optional[date] = None

    estado: Optional[EstadoCobranza] = None
    tipo: Optional[TipoCobranza] = None
    etapa_cobranza: Optional[str] = None
    ejecutivo_id: Optional[UUID] = None
    observaciones: Optional[str] = None
    datos_extra: Optional[dict] = None


class CobranzaResponse(CobranzaBase):
    """Cobranza tal como se devuelve al frontend (datos planos)."""
    id: UUID
    numero: int
    cliente_id: UUID
    deudor_id: UUID
    monto_actual: Decimal
    created_at: datetime
    updated_at: datetime
    # Datos legibles para listados
    deudor_nombre: Optional[str] = None
    deudor_rut: Optional[str] = None
    cliente_nombre: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class CobranzaDetalle(CobranzaResponse):
    """
    Ficha completa de la cobranza con las entidades relacionadas anidadas.
    Se usa en GET /api/cobranzas/{id}.
    """
    cliente: Optional[ClienteResponse] = None
    filial: Optional[FilialResponse] = None
    deudor: Optional[DeudorResponse] = None
    terceros: List[TerceroEnCobranza] = Field(default_factory=list)

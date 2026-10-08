// Tipos TypeScript que reflejan los schemas Pydantic del backend.
// Si el backend cambia un schema, actualizar aquí.

// Usuario del equipo (pantalla de administración).
export interface Usuario {
  id: string
  nombre: string
  email: string
  rol_id: number
  rol_nombre: string | null
  cliente_id: string | null
  activo: boolean
  mfa_activo: boolean
  debe_cambiar_password: boolean
  bloqueado: boolean
  ultimo_acceso?: string | null
  created_at?: string
}

// El usuario con sesión iniciada, con su organización y plan.
export interface UsuarioActual {
  id: string
  nombre: string
  email: string
  rol_id: number
  rol: string
  cliente_id: string | null
  mfa_activo: boolean
  debe_cambiar_password: boolean
  organizacion: {
    id: string
    nombre: string
    plan: 'base' | 'profesional' | 'premium'
    estado: string
    funciones: string[]
    etiquetas: Record<string, string>
  }
}

export interface SesionActiva {
  id: string
  creada_at: string
  ultimo_uso_at: string
  ip: string | null
  user_agent: string | null
  actual: boolean
}

export type TipoCampo = 'texto' | 'numero' | 'monto' | 'fecha' | 'seleccion' | 'si_no'

// Campo que la organización agregó a sus cobranzas o deudores.
export interface CampoPersonalizado {
  id: string
  entidad: 'cobranza' | 'deudor'
  clave: string
  etiqueta: string
  tipo: TipoCampo
  opciones: string[]
  cliente_id: string | null
  obligatorio: boolean
  orden: number
  activo: boolean
}

export type DatosExtra = Record<string, string | boolean>

export interface Rol {
  id: number
  nombre: string
  descripcion: string | null
}

export interface Cliente {
  id: string
  rut: string
  razon_social: string
  nombre_fantasia: string | null
  instrucciones_pago?: string | null
}

export interface Filial {
  id: number
  cliente_id: string
  nombre: string
  activo: boolean
}

export interface Deudor {
  id: string
  rut: string
  tipo: 'natural' | 'juridica'
  nombre: string
  comuna: string | null
  ciudad: string | null
  direccion?: string | null
  departamento?: string | null
  region?: string | null
  empleador?: string | null
  cargo?: string | null
  telefono_trabajo?: string | null
  contacto_alt_nombre?: string | null
  contacto_alt_relacion?: string | null
  contacto_alt_telefono?: string | null
  en_boletin_comercial: boolean
  observaciones: string | null
  datos_extra: DatosExtra
}

export interface Contacto {
  id: string
  deudor_id: string
  tipo: 'telefono' | 'celular' | 'email' | 'whatsapp' | 'otro'
  valor: string
  activo: boolean
}

export interface DeudorBusqueda extends Deudor {
  total_cobranzas: number
  cobranzas_abiertas: number
  saldo_abierto: number
}

export interface DeudorDetalle extends Deudor {
  contactos: Contacto[]
}

export type EstadoCobranza =
  | 'activa' | 'acuerdo_pago' | 'judicial' | 'pagada' | 'archivada' | 'castigo'

export type TipoDocumento =
  | 'pagare' | 'factura' | 'letra' | 'cheque' | 'contrato' | 'boleta' | 'credito' | 'otro'

export interface Cobranza {
  id: string
  numero: number
  cliente_id: string
  deudor_id: string
  filial_id: number | null
  id_externo: string | null
  monto_original: string
  monto_actual: string
  tipo_documento: TipoDocumento
  numero_documento: string | null
  fecha_vencimiento_documento: string | null
  fecha_origen: string | null
  numero_operacion: string | null
  estado: EstadoCobranza
  tipo: 'extrajudicial' | 'judicial'
  fecha_ingreso: string | null
  observaciones: string | null
  datos_extra: DatosExtra
  // Para listados
  deudor_nombre?: string | null
  deudor_rut?: string | null
  cliente_nombre?: string | null
}

export interface TerceroEnCobranza {
  tercero_id: string
  rol: string
  nombre: string
  rut: string | null
}

export interface CobranzaDetalle extends Cobranza {
  cliente: Cliente | null
  filial: Filial | null
  deudor: Deudor | null
  terceros: TerceroEnCobranza[]
}

export interface TipoGestion {
  id: number
  nombre: string
  codigo: string | null
  categoria: 'contacto' | 'pago' | 'negativo' | 'judicial' | 'otro'
  activo: boolean
  propio: boolean
}

export interface Gestion {
  id: string
  cobranza_id: string
  usuario_id: string
  usuario_nombre: string | null
  es_masivo: boolean
  tipo_id: number | null
  descripcion: string
  fecha_gestion: string
  fecha_proximo_contacto: string | null
}

export type EstadoAcuerdo = 'vigente' | 'cumplido' | 'incumplido' | 'renegociado'
export type EstadoCuota = 'pendiente' | 'pagada' | 'vencida' | 'pagada_parcial'

export interface Cuota {
  id: string
  acuerdo_id: string
  numero_cuota: number
  monto: string
  fecha_vencimiento: string
  monto_pagado: string
  estado: EstadoCuota
  // Desglose (acuerdos creados con la calculadora)
  capital?: string | null
  intereses?: string | null
  honorarios?: string | null
  gastos_judiciales?: string | null
  comision?: string | null
}

export interface Acuerdo {
  id: string
  cobranza_id: string
  estado: EstadoAcuerdo
  fecha_acuerdo: string | null
  fecha_termino: string | null
  pie: string
  monto_total_acordado: string
  numero_cuotas: number
  dia_pago: number | null
  fecha_primera_cuota: string
}

export interface AcuerdoDetalle extends Acuerdo {
  cuotas: Cuota[]
}

export type FormaPago =
  | 'transferencia' | 'cheque' | 'efectivo' | 'deposito'
  | 'flow' | 'presencial' | 'bonificacion' | 'otro'

export interface Pago {
  id: string
  cobranza_id: string
  cuota_id: string | null
  fecha_pago: string
  monto: string
  capital: string
  honorarios: string
  intereses: string
  gastos_judiciales: string
  forma_pago: FormaPago | null
  numero_comprobante: string | null
  estado_pago: 'pagado' | 'abono' | 'cuota' | 'bonificacion'
}

export interface ReporteUsuario {
  usuario_id: string
  nombre: string
  activo: boolean
  gestiones_total: number
  gestiones_por_tipo: Record<string, number>
  acuerdos_creados: number
  pagos_ingresados: number
  monto_pagos: string
}

// Datos institucionales de la organización (tabla `empresa`).
// De acá salen el membrete y el pie de los documentos Word.
export interface Empresa {
  razon_social: string
  nombre_fantasia: string | null
  rut: string | null
  wordmark: string
  bajada: string | null
  firma_documentos: string | null
  direccion: string | null
  ciudad: string | null
  horario_atencion: string | null
  telefonos: string | null
  emails: string | null
  sitio_web: string | null
  instrucciones_pago: string | null
  tiene_logo?: boolean
  logo_actualizado_at?: string | null
  updated_at?: string | null
}

// ---------- Fase 2: agenda, calculadora, mensaje de pago ----------

export type TipoItemAgenda = 'contacto' | 'promesa' | 'cuota' | 'recordatorio'

export interface ItemAgenda {
  tipo: TipoItemAgenda
  fecha: string
  hora: string | null
  titulo: string
  detalle: string | null
  atrasado: boolean
  cobranza_id: string | null
  numero_cobranza: number | null
  deudor: string | null
  monto: number | null
  responsable_id: string | null
  recordatorio_id: string | null
  cuota_id: string | null
}

export interface Recordatorio {
  id: string
  usuario_id: string
  cobranza_id: string | null
  fecha: string
  hora: string | null
  titulo: string
  nota: string | null
  estado: 'pendiente' | 'hecho' | 'descartado'
}

export interface ValorUF {
  fecha: string
  valor: string
  fuente: string | null
}

export type Modalidad = 'extrajudicial' | 'judicial'

export interface TramoHonorarios {
  desde_uf: string
  hasta_uf: string | null
  porcentaje: string
  monto_base: string
  honorarios: string
}

export interface ResultadoHonorarios {
  modalidad: Modalidad
  capital: string
  uf: string | null
  capital_uf: string | null
  tramos: TramoHonorarios[]
  total_honorarios: string
  total_deuda: string
}

export interface FilaPlan {
  numero: number
  fecha: string | null
  capital: string
  intereses: string
  honorarios: string
  gastos_judiciales: string
  comision: string
  total: string
}

export interface PlanAcuerdo {
  modalidad: Modalidad
  capital: string
  abono_inicial: string
  capital_pie: string
  honorarios_pie: string
  capital_en_cuotas: string
  numero_cuotas: number
  tasa_mensual: string
  uf: string | null
  cuota_capital: string
  interes_mensual: string
  honorarios_cuota: string
  gastos_judiciales: string
  comision_pct: string
  comision_total: string
  ajuste: string
  valor_cuota: string
  total_intereses: string
  total_honorarios: string
  total_en_cuotas: string
  gran_total: string
  cuotas: FilaPlan[]
  texto: string
}

export interface MensajePago {
  texto: string
  asunto: string
  telefono: string | null
  email: string | null
  whatsapp_url: string | null
  mailto_url: string | null
  falta_datos_pago: boolean
}

// ---------- Portal de mandantes ----------

export interface ResumenPortal {
  cliente: string
  estudio: string
  asignado: string
  saldo_abierto: string
  casos_abiertos: number
  casos_totales: number
  recuperado_total: string
  recuperado_mes: string
  acuerdos_vigentes: number
  acuerdos_por_aprobar: number
  meses: { mes: string; capital: string }[]
}

export interface CobranzaPortal {
  id: string
  numero: number
  id_externo: string | null
  deudor: string
  rut: string
  monto_original: string
  monto_actual: string
  estado: EstadoCobranza
  fecha_ingreso: string | null
  ultima_gestion: string | null
}

export interface FichaPortal extends CobranzaPortal {
  gestiones: { fecha: string; tipo: string | null; descripcion: string }[]
  pagos: { fecha_pago: string; monto: string; capital: string; forma_pago: FormaPago | null }[]
  acuerdo: (AcuerdoDetalle & { firma_cliente: FirmaCliente; observaciones: string | null }) | null
}

export type FirmaCliente = 'sin_firmar' | 'pendiente' | 'firmado_confirmado'

export interface AcuerdoPendiente {
  id: string
  cobranza_id: string
  numero_cobranza: number
  deudor: string
  fecha_acuerdo: string
  pie: string
  monto_total_acordado: string
  numero_cuotas: number
  firma_cliente: FirmaCliente
  observaciones: string | null
}

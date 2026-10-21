// Tipos del ciclo de vida y del módulo judicial (espejo de
// backend/app/schemas/judicial.py).

export type EtapaProcesal = 'demanda' | 'notificacion' | 'embargo' | 'defensa' | 'remate'
export type EstadoPaso = 'hecho' | 'actual' | 'pendiente' | 'omitido'

export interface PasoCiclo {
  clave: string
  nombre: string
  grupo: string | null
  estado: EstadoPaso
}

export interface CausaEnCiclo {
  id: string
  rol: string | null
  procedimiento: string
  etapa_procesal: EtapaProcesal
  estado: 'vigente' | 'terminada'
  resultado: string | null
  fecha_ingreso: string
  fecha_termino: string | null
  tribunal: string | null
}

export interface CicloVida {
  cobranza_id: string
  etapa: 'ingreso' | 'extrajudicial' | 'para_demanda' | 'judicial'
  etapa_desde: string
  dias_en_etapa: number | null
  paso_actual: string
  pasos: PasoCiclo[]
  estado: string
  motivo_cierre: string | null
  motivo_cierre_nombre: string | null
  fecha_cierre: string | null
  fecha_prescripcion: string | null
  prescripcion_proxima: boolean
  causas: CausaEnCiclo[]
  historial: { etapa_anterior: string | null; etapa_nueva: string; motivo: string | null; created_at: string; usuario: string | null }[]
}

export interface Catalogos {
  procedimientos: Record<string, string>
  etapas: Record<EtapaProcesal, string>
  resultados: Record<string, string>
  motivos_cierre: Record<string, string>
  tipos_bien: Record<string, string>
  estados_embargo: Record<string, string>
  tipos_gasto: Record<string, string>
  estados_gasto: Record<string, string>
}

export interface Tribunal {
  id: number
  nombre: string
  ciudad: string | null
  competencia: string
  propio: boolean
}

export interface TipoTramite {
  id: number
  codigo: string | null
  nombre: string
  etapa: EtapaProcesal | null
  plazo_dias: number | null
  siguiente_id: number | null
  genera_gasto: boolean
  alerta: boolean
  nota: string | null
  resultado: string | null
  orden: number
  activo: boolean
  propio: boolean
}

export interface CausaFila {
  id: string
  rol: string | null
  procedimiento: string
  etapa_procesal: EtapaProcesal
  estado: 'vigente' | 'terminada'
  resultado: string | null
  fecha_ingreso: string
  fecha_termino: string | null
  cuantia: string | null
  caratula: string | null
  tribunal: string | null
  deudor: string
  deudor_rut: string | null
  cliente: string
  abogado: string | null
  procurador: string | null
  ultima_fecha: string | null
  ultimo_tramite: string | null
  plazo_fecha: string | null
  siguiente_nombre: string | null
  numeros_cobranza: number[] | null
  dias_sin_movimiento: number | null
}

export interface Tramite {
  id: string
  causa_id: string
  tipo_id: number | null
  tipo_nombre: string | null
  fecha: string
  descripcion: string | null
  plazo_fecha: string | null
  siguiente_id: number | null
  siguiente_nombre: string | null
  usuario_nombre: string | null
  created_at: string
}

export interface Embargo {
  id: string
  causa_id: string
  tipo_bien: string
  descripcion: string
  estado: string
  fecha_traba: string | null
  inscripcion: string | null
  depositario: string | null
  monto_tasacion: string | null
  fecha_remate: string | null
  monto_remate: string | null
  observaciones: string | null
}

export interface Gasto {
  id: string
  cliente_id: string
  cliente_nombre: string | null
  cobranza_id: string | null
  numero_cobranza: number | null
  causa_id: string | null
  rol_causa: string | null
  tramite_id: string | null
  fecha: string
  tipo: string
  concepto: string
  monto: string
  proveedor: string | null
  numero_boleta: string | null
  estado: 'por_rendir' | 'rendido' | 'reembolsado' | 'no_reembolsable' | 'anulado'
  rendicion_id: string | null
  numero_rendicion: number | null
  fecha_reembolso: string | null
  observaciones: string | null
  created_at: string
}

export interface CausaDetalle {
  id: string
  rol: string | null
  tribunal_id: number | null
  tribunal: string | null
  procedimiento: string
  procedimiento_nombre: string
  etapa_procesal: EtapaProcesal
  estado: 'vigente' | 'terminada'
  resultado: string | null
  fecha_ingreso: string
  fecha_termino: string | null
  cuantia: string | null
  caratula: string | null
  cliente_id: string
  cliente: string
  deudor_id: string
  deudor: string
  deudor_rut: string | null
  abogado_id: string | null
  abogado: string | null
  procurador_id: string | null
  procurador: string | null
  observaciones: string | null
  cobranzas: { id: string; numero: number; id_externo: string | null; tipo_documento: string | null;
    numero_documento: string | null; monto_original: string; monto_actual: string; estado: string }[]
  tramites: Tramite[]
  embargos: Embargo[]
  gastos: Gasto[]
  plazo_fecha: string | null
  siguiente_id: number | null
  siguiente_nombre: string | null
  dias_sin_movimiento: number
  riesgo_abandono: boolean
  total_gastos: string
}

export interface TramiteRegistrado {
  tramite: Tramite
  etapa_procesal: EtapaProcesal
  propone_resultado: string | null
  gasto_id: string | null
}

export interface ResumenJudicial {
  vigentes: number
  por_etapa: Record<EtapaProcesal, number>
  plazos_vencidos: number
  plazos_hoy: number
  plazos_semana: number
  riesgo_abandono: number
  para_demanda: number
}

export interface CobranzaParaDemanda {
  id: string
  numero: number
  monto_actual: string
  fecha_ingreso: string
  etapa: string
  etapa_desde: string
  tipo_documento: string | null
  fecha_vencimiento_documento: string | null
  deudor: string
  deudor_rut: string | null
  cliente: string
  dias_para_demanda: number | null
  dias_en_cartera: number
  ultima_gestion: string | null
  fecha_prescripcion: string | null
}

export interface Rendicion {
  id: string
  numero: number
  cliente_id: string
  cliente_nombre: string | null
  fecha: string
  total: string
  estado: 'enviada' | 'pagada' | 'anulada'
  fecha_pago: string | null
  observaciones: string | null
  cantidad: number
  created_at: string
}

export interface RendicionDetalle extends Rendicion {
  gastos: Gasto[]
}

export interface ResumenGastosCliente {
  cliente_id: string
  cliente: string
  por_rendir: string
  cantidad_por_rendir: number
  rendido: string
  reembolsado: string
  total_adeudado: string
}

/*
 * MODO DEMO: módulo judicial simulado en el navegador (ver demo.ts).
 *
 * Replica lo esencial del backend (app/judicial.py, app/ciclo.py y
 * routers/judicial.py, routers/gastos.py): ciclo de vida de la cobranza,
 * causas con varias cobranzas, trámites con plazo y trámite siguiente,
 * embargos, término de causa, gastos y rendiciones. Los datos viven en el
 * localStorage de quien mira la demo.
 */

type Fila = Record<string, unknown>

export interface CausaDemo {
  id: string; rol: string | null; tribunal_id: number | null; procedimiento: string; etapa_procesal: string
  estado: 'vigente' | 'terminada'; resultado: string | null; fecha_ingreso: string; fecha_termino: string | null
  cuantia: number; caratula: string; cliente_id: string; deudor_id: string; abogado_id: string | null
  procurador_id: string | null; observaciones: string | null; cobranza_ids: string[]
}
export interface TramiteDemo {
  id: string; causa_id: string; tipo_id: number | null; fecha: string; descripcion: string | null
  plazo_fecha: string | null; siguiente_id: number | null; usuario_id: string; created_at: string
}
interface EmbargoDemo extends Fila { id: string; causa_id: string; estado: string }
interface GastoDemo {
  id: string; cliente_id: string; cobranza_id: string | null; causa_id: string | null; tramite_id: string | null
  fecha: string; tipo: string; concepto: string; monto: number; proveedor: string | null; numero_boleta: string | null
  estado: string; rendicion_id: string | null; fecha_reembolso: string | null; observaciones: string | null
  usuario_id: string; created_at: string
}
interface RendicionDemo {
  id: string; numero: number; cliente_id: string; fecha: string; total: number; estado: string
  fecha_pago: string | null; observaciones: string | null; created_at: string
}
interface CambioDemo { etapa_anterior: string | null; etapa_nueva: string; motivo: string | null; created_at: string; usuario: string | null }

export interface JudicialDemo {
  causas: CausaDemo[]
  tramites: TramiteDemo[]
  embargos: EmbargoDemo[]
  gastos: GastoDemo[]
  rendiciones: RendicionDemo[]
  /** Etapa guardada (para_demanda / judicial); si no hay, se deduce. */
  etapas: Record<string, string>
  historial: Record<string, CambioDemo[]>
  documentos?: DocumentoDemo[]
}

interface DocumentoDemo {
  id: string; cobranza_id: string; tipo: string; numero: string | null; fecha_emision: string | null
  fecha_vencimiento: string | null; monto: string | null; banco: string | null; plaza: string | null
  causal_protesto: string | null; fecha_protesto: string | null; observaciones: string | null; activo: boolean; created_at: string
}

const MESES_PRESCRIPCION: Record<string, number> = { cheque: 12, pagare: 12, letra: 12, factura: 12 }
function conPrescripcion(d: DocumentoDemo) {
  const base = d.tipo === 'cheque' && d.fecha_protesto ? d.fecha_protesto : d.fecha_vencimiento
  if (!base) return { ...d, fecha_prescripcion: null }
  const [a, m, dd] = base.split('-').map(Number)
  const total = m - 1 + (MESES_PRESCRIPCION[d.tipo] ?? 36)
  const anio = a + Math.floor(total / 12)
  const mes = (total % 12) + 1
  const dia = Math.min(dd, new Date(anio, mes, 0).getDate())
  return { ...d, fecha_prescripcion: `${anio}-${String(mes).padStart(2, '0')}-${String(dia).padStart(2, '0')}` }
}

interface CobranzaDemo {
  id: string; numero: number; cliente_id: string; deudor_id: string; estado: string; tipo: string
  monto_original: string | number; monto_actual: string | number; fecha_ingreso: string | null
  tipo_documento: string; numero_documento: string | null; id_externo: string | null
  fecha_vencimiento_documento?: string | null; fecha_traspaso?: string | null
  motivo_cierre?: string | null; fecha_cierre?: string | null
}
export interface BaseDemo {
  cobranzas: CobranzaDemo[]
  deudores: { id: string; nombre: string; rut: string }[]
  clientes: { id: string; razon_social: string; nombre_fantasia: string | null; dias_para_demanda?: number | null }[]
  usuarios: { id: string; nombre: string; rol_id: number; activo: boolean }[]
  gestiones: { cobranza_id: string; fecha_gestion: string }[]
  judicial?: JudicialDemo
}

export interface Ayudas {
  ok: (data: unknown, status?: number, headers?: Record<string, string>) => unknown
  error: (status: number, detalle: string) => unknown
  cuerpo: () => Record<string, unknown>
  usuarioId: string
  uid: () => string
  hoy: () => string
  ahora: () => string
  gestion: (cobranzaId: string, codigo: string, texto: string) => void
}

// ------------------------------------------------------------------ catálogos

export const PROCEDIMIENTOS: Record<string, string> = {
  ejecutivo: 'Juicio ejecutivo', notificacion_cheque: 'Notificación de protesto de cheque',
  notificacion_factura: 'Notificación de factura', notificacion_letra: 'Notificación de protesto de letra o pagaré',
  confesion_deuda: 'Citación a confesar deuda o reconocer firma', ordinario: 'Juicio ordinario',
  sumario: 'Juicio sumario', exhorto: 'Exhorto', liquidacion: 'Verificación de crédito en liquidación',
  querella: 'Querella criminal', otro: 'Otro',
}
const ETAPAS: Record<string, string> = {
  demanda: 'Demanda', notificacion: 'Notificación', embargo: 'Embargo', defensa: 'Excepciones y sentencia',
  remate: 'Remate y pago',
}
const RESULTADOS: Record<string, [string, string, string | null]> = {
  pagada: ['Pagada', 'pagada', 'pagada'], avenimiento_cumplido: ['Avenimiento cumplido', 'pagada', 'avenimiento_cumplido'],
  castigo: ['Castigo', 'castigo', null], desistida: ['Desistimiento', 'archivada', 'desistida'],
  abandono: ['Abandono del procedimiento', 'archivada', 'abandono'], prescrita: ['Acción prescrita', 'castigo', 'prescrita'],
  archivada: ['Archivada', 'archivada', 'otro'], devuelta: ['Devuelta al cliente', 'archivada', 'devuelta_cliente'],
}
const MOTIVOS: Record<string, string> = {
  pagada: 'Pagada', avenimiento_cumplido: 'Avenimiento cumplido', inubicable: 'Deudor inubicable',
  sin_bienes: 'Sin bienes embargables', liquidacion: 'Deudor en liquidación (quiebra)', fallecido: 'Deudor fallecido',
  antieconomico: 'Antieconómico seguir', prescrita: 'Acción prescrita', abandono: 'Abandono del procedimiento',
  desistida: 'Desistimiento', devuelta_cliente: 'Devuelta al cliente', suspendida_cliente: 'Suspendida por el cliente',
  otro: 'Otro motivo',
}
const TIPOS_BIEN = { vehiculo: 'Vehículo', inmueble: 'Inmueble', cuenta_bancaria: 'Cuenta bancaria', remuneraciones: 'Remuneraciones', muebles: 'Bienes muebles', otro: 'Otro' }
const ESTADOS_EMBARGO = { solicitado: 'Solicitado', trabado: 'Trabado', frustrado: 'Frustrado', retirado: 'Retirado', rematado: 'Rematado', alzado: 'Alzado' }
const TIPOS_GASTO = { receptor: 'Receptor', notificacion: 'Notificación', embargo: 'Embargo', fuerza_publica: 'Fuerza pública', conservador: 'Conservador', copias: 'Copias y certificados', publicacion: 'Publicación', martillero: 'Martillero', correo: 'Correo y cartas', otro: 'Otro' }
const ESTADOS_GASTO = { por_rendir: 'Por rendir', rendido: 'Rendido (por reembolsar)', reembolsado: 'Reembolsado', no_reembolsable: 'No reembolsable', anulado: 'Anulado' }

const TRIBUNALES = [
  ...[1, 2, 3, 4, 5].map((i) => [`${i}° Juzgado Civil de Valparaíso`, 'Valparaíso']),
  ...[1, 2, 3].map((i) => [`${i}° Juzgado Civil de Viña del Mar`, 'Viña del Mar']),
  ['1° Juzgado Civil de Quilpué', 'Quilpué'], ['Juzgado de Letras de Villa Alemana', 'Villa Alemana'],
  ...[1, 2, 3, 4, 5].map((i) => [`${i}° Juzgado Civil de Santiago`, 'Santiago']),
].map(([nombre, ciudad], i) => ({ id: i + 1, nombre, ciudad, competencia: 'civil', activo: true, propio: false }))

// Selección del catálogo del sistema: (código, nombre, etapa, plazo, siguiente, gasto, alerta, nota, resultado)
const CATALOGO: [string, string, string | null, number | null, string | null, boolean, boolean, string | null, string | null][] = [
  ['demanda_presentada', 'Se presenta demanda y documentos al tribunal', 'demanda', 10, 'distribucion_rol', false, false, null, null],
  ['distribucion_rol', 'Distribución e ingreso de rol', 'demanda', 5, 'acompana_documentos', false, false, 'Anotar el rol y el tribunal en la causa.', null],
  ['acompana_documentos', 'Acompaña documentos y custodia del título', 'demanda', 5, 'mandamiento', false, false, null, null],
  ['mandamiento', 'Encargado mandamiento de ejecución y embargo', 'demanda', 10, 'encarga_notificacion', true, false, null, null],
  ['citacion_confesar', 'Se presenta citación a confesar deuda o reconocer firma', 'demanda', 10, 'notificada_confesion', false, false, null, null],
  ['demanda_ejecutiva', 'Se presenta demanda ejecutiva (tras la gestión preparatoria)', 'demanda', 5, 'mandamiento', false, false, null, null],
  ['encarga_notificacion', 'Encarga notificación al receptor', 'notificacion', 30, 'notificado_requerido', true, false, null, null],
  ['busqueda_positiva', 'Búsqueda positiva: el deudor vive en el domicilio', 'notificacion', 10, 'pide_art44', true, false, 'Conseguir copia del estampado del receptor.', null],
  ['busqueda_negativa', 'Búsqueda negativa', 'notificacion', 10, 'nuevo_domicilio', true, false, null, null],
  ['pide_art44', 'Se pide notificación por artículo 44', 'notificacion', 20, 'notificado_art44', false, false, null, null],
  ['notificado_requerido', 'Notificado y requerido de pago', 'notificacion', 10, 'certificado_no_excepciones', true, true, 'Plazo para oponer excepciones: 4 días hábiles (8 si se notificó fuera de la comuna del tribunal).', null],
  ['notificado_art44', 'Notificado por artículo 44', 'notificacion', 10, 'certificado_no_excepciones', true, true, null, null],
  ['nuevo_domicilio', 'Señala nuevo domicilio', 'notificacion', 2, 'encarga_notificacion', false, false, null, null],
  ['notificado_protesto_cheque', 'Notificado el protesto de cheque', 'notificacion', 10, 'certificado_cheque', true, true, 'Plazo de 3 días para tachar de falsa la firma o consignar.', null],
  ['notificada_factura', 'Notificada la factura', 'notificacion', 10, 'certificado_no_tacha', true, false, 'Plazo de 3 días para alegar falsificación o falta de entrega.', null],
  ['notificada_confesion', 'Notificada la citación a confesar deuda o reconocer firma', 'notificacion', 3, 'confeso_deuda', true, true, 'Anotar fecha y hora de la audiencia.', null],
  ['certificado_no_excepciones', 'Certificado: no opuso excepciones', 'defensa', 15, 'embargo_bienes', false, false, null, null],
  ['opone_excepciones', 'El ejecutado opone excepciones', 'defensa', 4, 'contesta_excepciones', false, true, 'Informar al abogado: hay plazo para contestar el traslado.', null],
  ['contesta_excepciones', 'Contesta traslado de excepciones', 'defensa', 10, 'sentencia', false, false, null, null],
  ['certificado_cheque', 'Certificado de secretaría: no pagó ni tachó (cheque)', 'defensa', 10, 'demanda_ejecutiva', false, false, null, null],
  ['certificado_no_tacha', 'Certificado: no opuso tacha de falsedad', 'defensa', 20, 'demanda_ejecutiva', false, false, null, null],
  ['confeso_deuda', 'Deudor reconoce la deuda o firma, o no comparece', 'defensa', 5, 'demanda_ejecutiva', false, false, null, null],
  ['sentencia', 'Se dicta sentencia', 'defensa', 10, null, false, true, 'Revisar si es favorable y si conviene apelar.', null],
  ['embargo_bienes', 'Se embargan bienes muebles', 'embargo', 15, 'designacion_martillero', true, false, 'Registrar el embargo en la pestaña Embargos.', null],
  ['embargo_vehiculo', 'Se embarga vehículo', 'embargo', 15, 'designacion_martillero', true, false, 'Inscribir en el Registro de Vehículos Motorizados.', null],
  ['embargo_frustrado', 'Embargo frustrado: no se encontraron bienes', 'embargo', 10, 'certificado_castigo', true, false, null, null],
  ['designacion_martillero', 'Designación de martillero', 'remate', 10, 'fecha_remate', false, false, null, null],
  ['fecha_remate', 'Se fija fecha de remate', 'remate', 30, 'liquidacion_credito', true, true, 'Registrar el monto del remate.', null],
  ['liquidacion_credito', 'Se solicita liquidación del crédito', 'remate', 30, 'giro_cheque', false, true, null, null],
  ['giro_cheque', 'Se solicita giro de cheque', 'remate', 20, 'da_cuenta_pago', false, false, null, null],
  ['da_cuenta_pago', 'Se da cuenta de pago en el tribunal', null, null, null, false, false, null, 'pagada'],
  ['avenimiento', 'Avenimiento judicial', null, 90, null, false, false, 'Revisar el cumplimiento cada 90 días.', null],
  ['certificado_castigo', 'Se solicita certificado para castigo', null, 20, 'carta_castigo', true, false, null, null],
  ['carta_castigo', 'Carta de castigo al cliente', null, null, null, false, false, null, 'castigo'],
  ['reitera_receptor', 'Se reitera el encargo al receptor', null, 15, null, false, false, 'Apurar la diligencia encargada.', null],
]
export const TIPOS_TRAMITE = CATALOGO.map(([codigo, nombre, etapa, plazo_dias, , genera_gasto, alerta, nota, resultado], i) => ({
  id: i + 1, codigo, nombre, etapa, plazo_dias, siguiente_id: null as number | null, genera_gasto, alerta, nota, resultado,
  orden: i, activo: true, propio: false,
}))
for (const [i, fila] of CATALOGO.entries()) {
  const sig = fila[4] ? TIPOS_TRAMITE.find((t) => t.codigo === fila[4]) : undefined
  TIPOS_TRAMITE[i].siguiente_id = sig?.id ?? null
}
const tipoPorCodigo = (c: string) => TIPOS_TRAMITE.find((t) => t.codigo === c)!
const INICIAL: Record<string, string> = { confesion_deuda: 'citacion_confesar', querella: 'demanda_presentada' }

// ------------------------------------------------------------------ utilidades

const masDias = (iso: string, dias: number) => {
  const [a, m, d] = iso.split('-').map(Number)
  const f = new Date(a, m - 1, d + dias)
  return `${f.getFullYear()}-${String(f.getMonth() + 1).padStart(2, '0')}-${String(f.getDate()).padStart(2, '0')}`
}
const diasEntre = (desde: string, hasta: string) => {
  const [a, m, d] = desde.split('-').map(Number)
  const [b, n, e] = hasta.split('-').map(Number)
  return Math.round((new Date(b, n - 1, e).getTime() - new Date(a, m - 1, d).getTime()) / 86_400_000)
}
const TERMINALES = ['pagada', 'archivada', 'castigo']

export function etapaDe(db: BaseDemo, c: CobranzaDemo): string {
  const guardada = db.judicial?.etapas[c.id]
  if (guardada) return guardada
  if (c.estado === 'judicial') return 'judicial'
  return db.gestiones.some((g) => g.cobranza_id === c.id) ? 'extrajudicial' : 'ingreso'
}

function ultimoTramite(j: JudicialDemo, causaId: string): TramiteDemo | undefined {
  return j.tramites.filter((t) => t.causa_id === causaId && t.tipo_id !== null)
    .sort((a, b) => b.fecha.localeCompare(a.fecha) || b.created_at.localeCompare(a.created_at))[0]
}

function nombreUsuario(db: BaseDemo, id: string | null) {
  return id ? db.usuarios.find((u) => u.id === id)?.nombre ?? null : null
}

function nombreCliente(db: BaseDemo, id: string) {
  const c = db.clientes.find((x) => x.id === id)
  return c ? (c.nombre_fantasia ?? c.razon_social) : ''
}

function registrarCambio(db: BaseDemo, a: Ayudas, cobranzaId: string, anterior: string, nueva: string, motivo: string) {
  const j = db.judicial!
  j.historial[cobranzaId] = [...(j.historial[cobranzaId] ?? []), {
    etapa_anterior: anterior, etapa_nueva: nueva, motivo, created_at: a.ahora(), usuario: nombreUsuario(db, a.usuarioId),
  }]
}

// ------------------------------------------------------------------ semilla

/** Causas de ejemplo sobre las cobranzas de práctica. Se llama una vez al crear la demo. */
export function semillaJudicial(db: BaseDemo, hoy: string): JudicialDemo {
  const j: JudicialDemo = { causas: [], tramites: [], embargos: [], gastos: [], rendiciones: [], etapas: {}, historial: {} }
  db.judicial = j
  const candidatas = db.cobranzas.filter((c) => c.estado === 'activa' && c.id.startsWith('cob-s')).slice(0, 10)
  // (procedimiento, días desde la demanda, códigos de trámites en orden, ¿terminada?)
  const planes: [string, number, string[], string | null][] = [
    ['ejecutivo', 95, ['demanda_presentada', 'distribucion_rol', 'acompana_documentos', 'mandamiento', 'encarga_notificacion', 'notificado_requerido', 'certificado_no_excepciones', 'embargo_vehiculo'], null],
    ['ejecutivo', 40, ['demanda_presentada', 'distribucion_rol', 'acompana_documentos', 'mandamiento', 'encarga_notificacion'], null],
    ['notificacion_cheque', 30, ['demanda_presentada', 'distribucion_rol', 'notificado_protesto_cheque'], null],
    ['confesion_deuda', 12, ['citacion_confesar'], null],
    ['ejecutivo', 200, ['demanda_presentada', 'distribucion_rol', 'mandamiento', 'encarga_notificacion', 'busqueda_positiva', 'pide_art44', 'notificado_art44', 'certificado_no_excepciones', 'embargo_bienes', 'designacion_martillero', 'fecha_remate'], null],
    ['ejecutivo', 320, ['demanda_presentada', 'distribucion_rol', 'encarga_notificacion', 'notificado_requerido', 'embargo_frustrado', 'certificado_castigo', 'carta_castigo'], 'castigo'],
  ]
  planes.forEach(([procedimiento, dias, codigos, resultado], k) => {
    const c = candidatas[k]
    if (!c) return
    const inicio = masDias(hoy, -dias)
    const causaId = `causa-${k + 1}`
    const causa: CausaDemo = {
      id: causaId, rol: `C-${1200 + k * 37}-${inicio.slice(0, 4)}`, tribunal_id: TRIBUNALES[k % 8].id, procedimiento,
      etapa_procesal: 'demanda', estado: 'vigente', resultado: null, fecha_ingreso: inicio, fecha_termino: null,
      cuantia: Number(c.monto_actual), caratula: `${nombreCliente(db, c.cliente_id)} con ${db.deudores.find((d) => d.id === c.deudor_id)?.nombre ?? ''}`,
      cliente_id: c.cliente_id, deudor_id: c.deudor_id, abogado_id: 'u-supervisor', procurador_id: 'u-operador',
      observaciones: null, cobranza_ids: [c.id],
    }
    j.causas.push(causa)
    c.estado = 'judicial'; c.tipo = 'judicial'; c.fecha_traspaso = inicio
    j.etapas[c.id] = 'judicial'
    j.historial[c.id] = [{ etapa_anterior: 'extrajudicial', etapa_nueva: 'judicial', motivo: `Demanda presentada rol ${causa.rol}`, created_at: `${inicio}T15:00:00`, usuario: 'Ana Torres' }]
    // Fechas repartidas entre la demanda y hoy; el último trámite deja su plazo.
    const paso = Math.max(1, Math.floor(dias / codigos.length))
    codigos.forEach((codigo, i) => {
      const tipo = tipoPorCodigo(codigo)
      const fecha = masDias(inicio, Math.min(dias - 1, i * paso))
      j.tramites.push({ id: `tr-${k}-${i}`, causa_id: causaId, tipo_id: tipo.id, fecha, descripcion: null,
        plazo_fecha: tipo.plazo_dias != null ? masDias(fecha, tipo.plazo_dias) : null, siguiente_id: tipo.siguiente_id,
        usuario_id: 'u-operador', created_at: `${fecha}T16:${String(10 + i).padStart(2, '0')}:00` })
      if (tipo.etapa) causa.etapa_procesal = tipo.etapa
      if (tipo.genera_gasto) {
        const reembolsado = diasEntre(fecha, hoy) > 60
        j.gastos.push({ id: `ga-${k}-${i}`, cliente_id: c.cliente_id, cobranza_id: null, causa_id: causaId, tramite_id: `tr-${k}-${i}`,
          fecha, tipo: 'receptor', concepto: tipo.nombre, monto: 18000 + ((k * 7 + i * 13) % 6) * 4000,
          proveedor: ['Receptor Muñoz', 'Receptora Soto', 'Receptor Fuentes'][i % 3], numero_boleta: String(4100 + k * 20 + i),
          estado: reembolsado ? 'reembolsado' : 'por_rendir', rendicion_id: null, fecha_reembolso: reembolsado ? masDias(fecha, 45) : null,
          observaciones: null, usuario_id: 'u-operador', created_at: `${fecha}T17:00:00` })
      }
      if (codigo === 'embargo_vehiculo' || codigo === 'embargo_bienes') {
        j.embargos.push({ id: `em-${k}`, causa_id: causaId, tipo_bien: codigo === 'embargo_vehiculo' ? 'vehiculo' : 'muebles',
          descripcion: codigo === 'embargo_vehiculo' ? 'Automóvil patente KXLP-23' : 'Televisor, refrigerador y living',
          estado: 'trabado', fecha_traba: fecha, inscripcion: null, depositario: null, monto_tasacion: null,
          fecha_remate: null, monto_remate: null, observaciones: null, creado_por: 'u-operador',
          created_at: `${fecha}T17:30:00`, updated_at: `${fecha}T17:30:00` })
      }
    })
    j.tramites.push({ id: `tr-${k}-obs`, causa_id: causaId, tipo_id: null, fecha: masDias(hoy, -2), descripcion: 'Se revisa el estado diario de la causa.',
      plazo_fecha: null, siguiente_id: null, usuario_id: 'u-operador', created_at: `${masDias(hoy, -2)}T11:00:00` })
    if (resultado) {
      causa.estado = 'terminada'; causa.resultado = resultado; causa.fecha_termino = masDias(hoy, -5)
      c.estado = 'castigo'; c.motivo_cierre = 'sin_bienes'; c.fecha_cierre = causa.fecha_termino
    }
  })
  // Dos cobranzas en preparación de demanda y un cliente con regla de días.
  for (const c of candidatas.slice(6, 8)) {
    j.etapas[c.id] = 'para_demanda'
    j.historial[c.id] = [{ etapa_anterior: 'extrajudicial', etapa_nueva: 'para_demanda', motivo: 'No responde a la cobranza extrajudicial', created_at: `${masDias(hoy, -3)}T12:00:00`, usuario: 'María Soto' }]
  }
  const clinica = db.clientes.find((c) => c.id === 'cl-1')
  if (clinica) clinica.dias_para_demanda = 120
  return j
}

// ------------------------------------------------------------------ vistas

function filaCausa(db: BaseDemo, c: CausaDemo, hoy: string) {
  const j = db.judicial!
  const u = ultimoTramite(j, c.id)
  const d = db.deudores.find((x) => x.id === c.deudor_id)
  const ultima = u?.fecha ?? c.fecha_ingreso
  return {
    id: c.id, rol: c.rol, procedimiento: c.procedimiento, etapa_procesal: c.etapa_procesal, estado: c.estado,
    resultado: c.resultado, fecha_ingreso: c.fecha_ingreso, fecha_termino: c.fecha_termino, cuantia: String(c.cuantia),
    caratula: c.caratula, tribunal: TRIBUNALES.find((t) => t.id === c.tribunal_id)?.nombre ?? null,
    deudor: d?.nombre ?? '', deudor_rut: d?.rut ?? null, cliente: nombreCliente(db, c.cliente_id),
    abogado: nombreUsuario(db, c.abogado_id), procurador: nombreUsuario(db, c.procurador_id),
    ultima_fecha: u?.fecha ?? null, ultimo_tramite: u ? TIPOS_TRAMITE.find((t) => t.id === u.tipo_id)?.nombre ?? null : null,
    plazo_fecha: c.estado === 'vigente' ? u?.plazo_fecha ?? null : null,
    siguiente_nombre: u?.siguiente_id ? TIPOS_TRAMITE.find((t) => t.id === u.siguiente_id)?.nombre ?? null : null,
    numeros_cobranza: c.cobranza_ids.map((id) => db.cobranzas.find((x) => x.id === id)?.numero ?? 0).sort((a, b) => a - b),
    dias_sin_movimiento: diasEntre(ultima, hoy),
  }
}

function vistaGasto(db: BaseDemo, g: GastoDemo) {
  const j = db.judicial!
  return {
    ...g, monto: String(g.monto), cliente_nombre: nombreCliente(db, g.cliente_id),
    numero_cobranza: g.cobranza_id ? db.cobranzas.find((c) => c.id === g.cobranza_id)?.numero ?? null : null,
    rol_causa: g.causa_id ? j.causas.find((c) => c.id === g.causa_id)?.rol ?? null : null,
    numero_rendicion: g.rendicion_id ? j.rendiciones.find((r) => r.id === g.rendicion_id)?.numero ?? null : null,
  }
}

function fichaCausa(db: BaseDemo, c: CausaDemo, hoy: string) {
  const j = db.judicial!
  const fila = filaCausa(db, c, hoy)
  const tramites = j.tramites.filter((t) => t.causa_id === c.id)
    .sort((a, b) => b.fecha.localeCompare(a.fecha) || b.created_at.localeCompare(a.created_at))
    .map((t) => ({ ...t, tipo_nombre: t.tipo_id ? TIPOS_TRAMITE.find((x) => x.id === t.tipo_id)?.nombre ?? null : null,
      siguiente_nombre: t.siguiente_id ? TIPOS_TRAMITE.find((x) => x.id === t.siguiente_id)?.nombre ?? null : null,
      usuario_nombre: nombreUsuario(db, t.usuario_id) }))
  const gastos = j.gastos.filter((g) => g.causa_id === c.id).sort((a, b) => b.fecha.localeCompare(a.fecha)).map((g) => vistaGasto(db, g))
  const ultimo = ultimoTramite(j, c.id)
  return {
    ...fila, tribunal_id: c.tribunal_id, procedimiento_nombre: PROCEDIMIENTOS[c.procedimiento] ?? c.procedimiento,
    cliente_id: c.cliente_id, deudor_id: c.deudor_id, abogado_id: c.abogado_id, procurador_id: c.procurador_id,
    observaciones: c.observaciones,
    cobranzas: c.cobranza_ids.map((id) => db.cobranzas.find((x) => x.id === id)).filter(Boolean).map((x) => ({
      id: x!.id, numero: x!.numero, id_externo: x!.id_externo, tipo_documento: x!.tipo_documento,
      numero_documento: x!.numero_documento, monto_original: String(x!.monto_original), monto_actual: String(x!.monto_actual), estado: x!.estado })),
    tramites, embargos: j.embargos.filter((e) => e.causa_id === c.id), gastos,
    siguiente_id: ultimo?.siguiente_id ?? null,
    riesgo_abandono: c.estado === 'vigente' && fila.dias_sin_movimiento >= 150,
    total_gastos: String(gastos.filter((g) => g.estado !== 'anulado').reduce((s, g) => s + Number(g.monto), 0)),
  }
}

/** Plazos judiciales para la agenda y los avisos de la demo. */
export function plazosDemo(db: BaseDemo, desde: string, hasta: string, hoy: string) {
  const j = db.judicial
  if (!j) return []
  return j.causas.filter((c) => c.estado === 'vigente').flatMap((c) => {
    const u = ultimoTramite(j, c.id)
    if (!u?.plazo_fecha || u.plazo_fecha < desde || u.plazo_fecha > hasta) return []
    const d = db.deudores.find((x) => x.id === c.deudor_id)
    const cob = db.cobranzas.find((x) => x.id === c.cobranza_ids[0])
    const tipo = TIPOS_TRAMITE.find((t) => t.id === u.tipo_id)
    const sig = TIPOS_TRAMITE.find((t) => t.id === u.siguiente_id)
    return [{ tipo: 'plazo', fecha: u.plazo_fecha, hora: null, titulo: `Plazo judicial: ${d?.nombre ?? ''} (rol ${c.rol})`,
      detalle: `Último trámite: ${tipo?.nombre}.${sig ? ` Sigue: ${sig.nombre}.` : ''}`, atrasado: u.plazo_fecha < hoy,
      cobranza_id: cob?.id ?? null, numero_cobranza: cob?.numero ?? null, deudor: d?.nombre ?? null, monto: null,
      responsable_id: c.procurador_id, recordatorio_id: null, cuota_id: null, causa_id: c.id }]
  })
}

/** Ciclo de vida completo (con causas e historial) para la barra de la ficha. */
export function cicloDemo(db: BaseDemo, c: CobranzaDemo, hoy: string) {
  const j = db.judicial
  const causas = (j?.causas ?? []).filter((x) => x.cobranza_ids.includes(c.id))
    .sort((a, b) => (a.estado === 'vigente' ? -1 : 1) - (b.estado === 'vigente' ? -1 : 1))
  const etapa = etapaDe(db, c)
  const cerrada = TERMINALES.includes(c.estado)
  const procesal = causas[0]?.etapa_procesal ?? 'demanda'
  const claves: [string, string, string | null][] = [
    ['ingreso', 'Ingreso', null], ['extrajudicial', 'Extrajudicial', null], ['para_demanda', 'Para demanda', null],
    ['demanda', 'Demanda', 'judicial'], ['notificacion', 'Notificación', 'judicial'], ['embargo', 'Embargo', 'judicial'],
    ['defensa', 'Excepciones y sentencia', 'judicial'], ['remate', 'Remate y pago', 'judicial'], ['termino', 'Término', null],
  ]
  const actual = cerrada ? 'termino' : etapa === 'judicial' ? procesal : etapa
  const alcanzado = etapa === 'judicial' ? procesal : etapa
  const idx = (k: string) => claves.findIndex(([x]) => x === k)
  const historial = j?.historial[c.id] ?? []
  const desde = historial[historial.length - 1]?.created_at.slice(0, 10) ?? c.fecha_ingreso ?? hoy
  return {
    cobranza_id: c.id, etapa, etapa_desde: desde, dias_en_etapa: diasEntre(desde, hoy), paso_actual: actual,
    pasos: claves.map(([clave, nombre, grupo]) => ({ clave, nombre, grupo,
      estado: cerrada ? (clave === 'termino' ? 'actual' : idx(clave) <= idx(alcanzado) ? 'hecho' : 'omitido')
        : clave === actual ? 'actual' : idx(clave) < idx(actual) ? 'hecho' : 'pendiente' })),
    estado: c.estado, motivo_cierre: c.motivo_cierre ?? (cerrada ? c.estado : null),
    motivo_cierre_nombre: cerrada ? MOTIVOS[c.motivo_cierre ?? ''] ?? ({ pagada: 'Pagada', archivada: 'Archivada', castigo: 'Castigo' } as Record<string, string>)[c.estado] : null,
    fecha_cierre: c.fecha_cierre ?? null, fecha_prescripcion: null, prescripcion_proxima: false,
    causas: causas.map((x) => ({ id: x.id, rol: x.rol, procedimiento: x.procedimiento, etapa_procesal: x.etapa_procesal,
      estado: x.estado, resultado: x.resultado, fecha_ingreso: x.fecha_ingreso, fecha_termino: x.fecha_termino,
      tribunal: TRIBUNALES.find((t) => t.id === x.tribunal_id)?.nombre ?? null })),
    historial,
  }
}

// ------------------------------------------------------------------ rutas

/** Atiende las rutas judiciales y de gastos; devuelve undefined si la ruta no es suya. */
export function manejarJudicial(db: BaseDemo, metodo: string, url: string, params: Record<string, string>, a: Ayudas): unknown {
  const j = db.judicial
  if (!j) return undefined
  const hoy = a.hoy()
  let m: RegExpExecArray | null

  // ---- ciclo de vida
  if (metodo === 'GET' && (m = /^\/cobranzas\/([^/]+)\/ciclo$/.exec(url))) {
    const c = db.cobranzas.find((x) => x.id === m![1])
    return c ? a.ok(cicloDemo(db, c, hoy)) : a.error(404, 'Cobranza no encontrada')
  }
  if (metodo === 'POST' && (m = /^\/cobranzas\/([^/]+)\/etapa$/.exec(url))) {
    const c = db.cobranzas.find((x) => x.id === m![1])
    if (!c) return a.error(404, 'Cobranza no encontrada')
    const { etapa, motivo } = a.cuerpo() as { etapa: string; motivo: string | null }
    const anterior = etapaDe(db, c)
    if (anterior === 'judicial') return a.error(400, 'La cobranza ya está en judicial: hay una demanda de por medio y no puede volver atrás.')
    if (TERMINALES.includes(c.estado)) return a.error(400, 'La cobranza está cerrada; reábrala antes de cambiar su etapa.')
    j.etapas[c.id] = etapa
    registrarCambio(db, a, c.id, anterior, etapa, motivo ?? '')
    return a.ok(cicloDemo(db, c, hoy))
  }

  // ---- documentos de la cobranza
  if ((m = /^\/cobranzas\/([^/]+)\/documentos$/.exec(url))) {
    const c = db.cobranzas.find((x) => x.id === m![1])
    if (!c) return a.error(404, 'Cobranza no encontrada')
    j.documentos ??= []
    if (!j.documentos.some((d) => d.cobranza_id === c.id)) {
      j.documentos.push({ id: `doc-${c.id}`, cobranza_id: c.id, tipo: c.tipo_documento, numero: c.numero_documento,
        fecha_emision: null, fecha_vencimiento: c.fecha_vencimiento_documento ?? null, monto: String(c.monto_original),
        banco: null, plaza: null, causal_protesto: null, fecha_protesto: null, observaciones: null, activo: true, created_at: a.ahora() })
    }
    if (metodo === 'POST') {
      const d = a.cuerpo() as Record<string, string | null>
      j.documentos.push({ id: a.uid(), cobranza_id: c.id, tipo: d.tipo ?? 'otro', numero: d.numero ?? null,
        fecha_emision: d.fecha_emision ?? null, fecha_vencimiento: d.fecha_vencimiento ?? null,
        monto: d.monto != null ? String(d.monto) : null, banco: d.banco ?? null, plaza: d.plaza ?? null,
        causal_protesto: d.causal_protesto ?? null, fecha_protesto: d.fecha_protesto ?? null, observaciones: null,
        activo: true, created_at: a.ahora() })
      return a.ok(conPrescripcion(j.documentos[j.documentos.length - 1]), 201)
    }
    return a.ok(j.documentos.filter((d) => d.cobranza_id === c.id && (d.activo || params.todos)).map(conPrescripcion))
  }
  if (metodo === 'PUT' && (m = /^\/cobranzas\/documentos\/([^/]+)$/.exec(url))) {
    const d = (j.documentos ?? []).find((x) => x.id === m![1])
    if (!d) return a.error(404, 'Documento no encontrado')
    Object.assign(d, a.cuerpo())
    return a.ok(conPrescripcion(d))
  }

  if (!url.startsWith('/judicial/') && !url.startsWith('/gastos/')) return undefined

  // ---- catálogos
  if (metodo === 'GET' && url === '/judicial/catalogos') {
    return a.ok({ procedimientos: PROCEDIMIENTOS, etapas: ETAPAS,
      resultados: Object.fromEntries(Object.entries(RESULTADOS).map(([k, v]) => [k, v[0]])), motivos_cierre: MOTIVOS,
      tipos_bien: TIPOS_BIEN, estados_embargo: ESTADOS_EMBARGO, tipos_gasto: TIPOS_GASTO, estados_gasto: ESTADOS_GASTO })
  }
  if (metodo === 'GET' && url === '/judicial/tribunales') return a.ok(TRIBUNALES)
  if (metodo === 'GET' && url === '/judicial/tipos-tramite') return a.ok(TIPOS_TRAMITE)
  if (metodo === 'GET' && url === '/judicial/equipo') {
    return a.ok(db.usuarios.filter((u) => u.activo && u.rol_id !== 7).map((u) => ({ id: u.id, nombre: u.nombre, rol: 'abogado' })))
  }

  // ---- bandeja
  const vigentes = j.causas.filter((c) => c.estado === 'vigente')
  if (metodo === 'GET' && url === '/judicial/resumen') {
    const filas = vigentes.map((c) => filaCausa(db, c, hoy))
    return a.ok({
      vigentes: vigentes.length,
      por_etapa: Object.fromEntries(Object.keys(ETAPAS).map((e) => [e, vigentes.filter((c) => c.etapa_procesal === e).length])),
      plazos_vencidos: filas.filter((f) => f.plazo_fecha && f.plazo_fecha < hoy).length,
      plazos_hoy: filas.filter((f) => f.plazo_fecha === hoy).length,
      plazos_semana: filas.filter((f) => f.plazo_fecha && f.plazo_fecha > hoy && f.plazo_fecha <= masDias(hoy, 7)).length,
      riesgo_abandono: filas.filter((f) => (f.dias_sin_movimiento ?? 0) >= 150).length,
      para_demanda: db.cobranzas.filter((c) => !TERMINALES.includes(c.estado) && etapaDe(db, c) === 'para_demanda').length,
    })
  }
  if (metodo === 'GET' && url === '/judicial/para-demanda') {
    const fila = (c: CobranzaDemo) => {
      const d = db.deudores.find((x) => x.id === c.deudor_id)
      const cl = db.clientes.find((x) => x.id === c.cliente_id)
      const ingreso = c.fecha_ingreso ?? hoy
      return { id: c.id, numero: c.numero, monto_actual: String(c.monto_actual), fecha_ingreso: ingreso, etapa: etapaDe(db, c),
        etapa_desde: ingreso, tipo_documento: c.tipo_documento, fecha_vencimiento_documento: c.fecha_vencimiento_documento ?? null,
        deudor: d?.nombre ?? '', deudor_rut: d?.rut ?? null, cliente: nombreCliente(db, c.cliente_id),
        dias_para_demanda: cl?.dias_para_demanda ?? null, dias_en_cartera: diasEntre(ingreso, hoy), ultima_gestion: null,
        fecha_prescripcion: null }
    }
    const abiertas = db.cobranzas.filter((c) => !TERMINALES.includes(c.estado))
    return a.ok({
      preparacion: abiertas.filter((c) => etapaDe(db, c) === 'para_demanda').map(fila),
      sugeridas: abiertas.filter((c) => {
        const dias = db.clientes.find((x) => x.id === c.cliente_id)?.dias_para_demanda
        return c.estado === 'activa' && ['ingreso', 'extrajudicial'].includes(etapaDe(db, c)) && dias != null
          && diasEntre(c.fecha_ingreso ?? hoy, hoy) >= dias
      }).slice(0, 50).map(fila),
    })
  }
  if (metodo === 'GET' && url === '/judicial/causas') {
    let lista = j.causas
    if (params.estado !== 'todas') lista = lista.filter((c) => c.estado === (params.estado || 'vigente'))
    if (params.etapa) lista = lista.filter((c) => c.etapa_procesal === params.etapa)
    if (params.mias) lista = lista.filter((c) => c.abogado_id === a.usuarioId || c.procurador_id === a.usuarioId)
    let filas = lista.map((c) => filaCausa(db, c, hoy))
    if (params.q) {
      const q = params.q.toLowerCase().replace(/\./g, '')
      filas = filas.filter((f) => (f.rol ?? '').toLowerCase().includes(q) || f.deudor.toLowerCase().includes(q)
        || (f.deudor_rut ?? '').includes(q) || (f.numeros_cobranza ?? []).map(String).includes(q))
    }
    if (params.plazo === 'vencido') filas = filas.filter((f) => f.plazo_fecha && f.plazo_fecha < hoy)
    if (params.plazo === 'semana') filas = filas.filter((f) => f.plazo_fecha && f.plazo_fecha >= hoy && f.plazo_fecha <= masDias(hoy, 7))
    if (params.plazo === 'abandono') filas = filas.filter((f) => (f.dias_sin_movimiento ?? 0) >= 150)
    filas.sort((x, y) => (x.plazo_fecha ?? '9999').localeCompare(y.plazo_fecha ?? '9999'))
    const desde = Number(params.skip) || 0
    return a.ok(filas.slice(desde, desde + (Number(params.limit) || 100)), 200, { 'x-total-count': String(filas.length) })
  }
  if (metodo === 'POST' && url === '/judicial/causas') {
    const d = a.cuerpo() as Record<string, unknown>
    const ids = (d.cobranza_ids as string[]) ?? []
    const cobs = ids.map((id) => db.cobranzas.find((c) => c.id === id)).filter(Boolean) as CobranzaDemo[]
    if (cobs.length === 0) return a.error(400, 'Indique al menos una cobranza para la demanda.')
    if (new Set(cobs.map((c) => `${c.cliente_id}|${c.deudor_id}`)).size > 1) {
      return a.error(400, 'Una demanda solo puede incluir cobranzas del mismo deudor y del mismo cliente.')
    }
    const primera = cobs[0]
    const fecha = (d.fecha_ingreso as string) || hoy
    const causa: CausaDemo = {
      id: a.uid(), rol: (d.rol as string) || null, tribunal_id: (d.tribunal_id as number) ?? null,
      procedimiento: (d.procedimiento as string) || 'ejecutivo', etapa_procesal: 'demanda', estado: 'vigente', resultado: null,
      fecha_ingreso: fecha, fecha_termino: null,
      cuantia: d.cuantia != null ? Number(d.cuantia) : cobs.reduce((s, c) => s + Number(c.monto_actual), 0),
      caratula: `${nombreCliente(db, primera.cliente_id)} con ${db.deudores.find((x) => x.id === primera.deudor_id)?.nombre ?? ''}`,
      cliente_id: primera.cliente_id, deudor_id: primera.deudor_id, abogado_id: (d.abogado_id as string) || null,
      procurador_id: (d.procurador_id as string) || null, observaciones: (d.observaciones as string) || null, cobranza_ids: ids,
    }
    j.causas.push(causa)
    const tribunal = TRIBUNALES.find((t) => t.id === causa.tribunal_id)?.nombre
    for (const c of cobs) {
      registrarCambio(db, a, c.id, etapaDe(db, c), 'judicial', `Demanda presentada${causa.rol ? ` rol ${causa.rol}` : ''}${tribunal ? ` en ${tribunal}` : ''}`)
      j.etapas[c.id] = 'judicial'
      c.estado = 'judicial'; c.tipo = 'judicial'
      a.gestion(c.id, 'demanda', `DEMANDA PRESENTADA: ${PROCEDIMIENTOS[causa.procedimiento]}${causa.rol ? `, rol ${causa.rol}` : ''}.`)
    }
    const tipo = tipoPorCodigo(INICIAL[causa.procedimiento] ?? 'demanda_presentada')
    j.tramites.push({ id: a.uid(), causa_id: causa.id, tipo_id: tipo.id, fecha, descripcion: null,
      plazo_fecha: tipo.plazo_dias != null ? masDias(fecha, tipo.plazo_dias) : null, siguiente_id: tipo.siguiente_id,
      usuario_id: a.usuarioId, created_at: a.ahora() })
    return a.ok(fichaCausa(db, causa, hoy), 201)
  }
  if ((m = /^\/judicial\/causas\/([^/]+)(\/[a-z]+)?$/.exec(url))) {
    const causa = j.causas.find((c) => c.id === m![1])
    if (!causa) return a.error(404, 'Causa no encontrada')
    const accion = m[2]
    if (metodo === 'GET' && !accion) return a.ok(fichaCausa(db, causa, hoy))
    if (metodo === 'PUT' && !accion) {
      Object.assign(causa, a.cuerpo())
      return a.ok(fichaCausa(db, causa, hoy))
    }
    if (metodo === 'POST' && accion === '/tramites') {
      if (causa.estado !== 'vigente') return a.error(400, 'La causa está terminada: no se pueden agregar trámites.')
      const d = a.cuerpo() as Record<string, unknown>
      const tipo = d.tipo_id ? TIPOS_TRAMITE.find((t) => t.id === Number(d.tipo_id)) : undefined
      const descripcion = ((d.descripcion as string) ?? '').trim() || null
      if (!tipo && !descripcion) return a.error(400, 'Escriba la observación o elija un trámite.')
      const fecha = (d.fecha as string) || hoy
      const tramite: TramiteDemo = { id: a.uid(), causa_id: causa.id, tipo_id: tipo?.id ?? null, fecha, descripcion,
        plazo_fecha: (d.plazo_fecha as string) || (tipo?.plazo_dias != null ? masDias(fecha, tipo.plazo_dias) : null),
        siguiente_id: tipo ? ((d.siguiente_id as number) ?? tipo.siguiente_id) : null, usuario_id: a.usuarioId, created_at: a.ahora() }
      j.tramites.push(tramite)
      if (tipo?.etapa) causa.etapa_procesal = tipo.etapa
      let gastoId: string | null = null
      const g = d.gasto as Record<string, unknown> | null
      if (g && Number(g.monto) > 0) {
        gastoId = a.uid()
        j.gastos.push({ id: gastoId, cliente_id: causa.cliente_id, cobranza_id: null, causa_id: causa.id, tramite_id: tramite.id,
          fecha: (g.fecha as string) || fecha, tipo: (g.tipo as string) || 'receptor', concepto: tipo?.nombre ?? 'Gasto judicial',
          monto: Number(g.monto), proveedor: (g.proveedor as string) || null, numero_boleta: (g.numero_boleta as string) || null,
          estado: 'por_rendir', rendicion_id: null, fecha_reembolso: null, observaciones: null, usuario_id: a.usuarioId, created_at: a.ahora() })
      }
      return a.ok({ tramite: { ...tramite, tipo_nombre: tipo?.nombre ?? null, siguiente_nombre: null, usuario_nombre: nombreUsuario(db, a.usuarioId) },
        etapa_procesal: causa.etapa_procesal, propone_resultado: tipo?.resultado ?? null, gasto_id: gastoId }, 201)
    }
    if (metodo === 'POST' && accion === '/terminar') {
      if (causa.estado !== 'vigente') return a.error(400, 'La causa ya está terminada.')
      const d = a.cuerpo() as { resultado: string; fecha?: string; motivo_cierre?: string | null; nota?: string | null }
      const [nombre, estado, motivoDefecto] = RESULTADOS[d.resultado] ?? RESULTADOS.archivada
      const fecha = d.fecha || hoy
      causa.estado = 'terminada'; causa.resultado = d.resultado; causa.fecha_termino = fecha
      j.tramites.push({ id: a.uid(), causa_id: causa.id, tipo_id: null, fecha, descripcion: `CAUSA TERMINADA: ${nombre}.${d.nota ? ' ' + d.nota : ''}`,
        plazo_fecha: null, siguiente_id: null, usuario_id: a.usuarioId, created_at: a.ahora() })
      for (const id of causa.cobranza_ids) {
        const c = db.cobranzas.find((x) => x.id === id)
        if (!c || TERMINALES.includes(c.estado)) continue
        c.estado = estado; c.motivo_cierre = d.motivo_cierre || motivoDefecto || 'otro'; c.fecha_cierre = fecha
        if (estado === 'pagada') c.monto_actual = '0'
        a.gestion(c.id, estado === 'pagada' ? 'pagado' : 'nota', `CAUSA TERMINADA (${causa.rol ?? 'sin rol'}): ${nombre}.`)
      }
      return a.ok(fichaCausa(db, causa, hoy))
    }
    if (metodo === 'POST' && accion === '/embargos') {
      const d = a.cuerpo()
      j.embargos.push({ ...d, id: a.uid(), causa_id: causa.id, estado: String(d.estado ?? 'trabado'), created_at: a.ahora(), updated_at: a.ahora() })
      return a.ok(j.embargos[j.embargos.length - 1], 201)
    }
    if (metodo === 'POST' && accion === '/cobranzas') {
      const { cobranza_id } = a.cuerpo() as { cobranza_id: string }
      const c = db.cobranzas.find((x) => x.id === cobranza_id)
      if (!c) return a.error(404, 'Cobranza no encontrada')
      if (c.deudor_id !== causa.deudor_id || c.cliente_id !== causa.cliente_id) {
        return a.error(400, 'Una demanda solo puede incluir cobranzas del mismo deudor y del mismo cliente.')
      }
      causa.cobranza_ids.push(c.id)
      registrarCambio(db, a, c.id, etapaDe(db, c), 'judicial', `Se agrega a la causa rol ${causa.rol ?? 's/n'}`)
      j.etapas[c.id] = 'judicial'; c.estado = 'judicial'; c.tipo = 'judicial'
      return a.ok(fichaCausa(db, causa, hoy))
    }
  }
  if (metodo === 'PUT' && (m = /^\/judicial\/embargos\/([^/]+)$/.exec(url))) {
    const e = j.embargos.find((x) => x.id === m![1])
    if (!e) return a.error(404, 'Embargo no encontrado')
    Object.assign(e, a.cuerpo(), { updated_at: a.ahora() })
    return a.ok(e)
  }

  // ---- gastos
  if (metodo === 'GET' && url === '/gastos/resumen') {
    const clientes = [...new Set(j.gastos.map((g) => g.cliente_id))]
    return a.ok(clientes.map((id) => {
      const de = j.gastos.filter((g) => g.cliente_id === id)
      const suma = (estado: string) => de.filter((g) => g.estado === estado).reduce((s, g) => s + g.monto, 0)
      return { cliente_id: id, cliente: nombreCliente(db, id), por_rendir: String(suma('por_rendir')),
        cantidad_por_rendir: de.filter((g) => g.estado === 'por_rendir').length, rendido: String(suma('rendido')),
        reembolsado: String(suma('reembolsado')), total_adeudado: String(suma('por_rendir') + suma('rendido')) }
    }))
  }
  if (metodo === 'GET' && url === '/gastos/') {
    let lista = j.gastos
    if (params.cliente_id) lista = lista.filter((g) => g.cliente_id === params.cliente_id)
    if (params.estado === 'adeudado') lista = lista.filter((g) => ['por_rendir', 'rendido'].includes(g.estado))
    else if (params.estado) lista = lista.filter((g) => g.estado === params.estado)
    if (params.causa_id) lista = lista.filter((g) => g.causa_id === params.causa_id)
    return a.ok([...lista].sort((x, y) => y.fecha.localeCompare(x.fecha)).map((g) => vistaGasto(db, g)), 200,
      { 'x-total-count': String(lista.length) })
  }
  if (metodo === 'POST' && url === '/gastos/') {
    const d = a.cuerpo() as Record<string, unknown>
    const causa = d.causa_id ? j.causas.find((c) => c.id === d.causa_id) : undefined
    const cob = d.cobranza_id ? db.cobranzas.find((c) => c.id === d.cobranza_id) : undefined
    const cliente = causa?.cliente_id ?? cob?.cliente_id
    if (!cliente) return a.error(422, 'Indique la causa o la cobranza del gasto.')
    const g: GastoDemo = { id: a.uid(), cliente_id: cliente, cobranza_id: (d.cobranza_id as string) ?? null,
      causa_id: (d.causa_id as string) ?? null, tramite_id: null, fecha: (d.fecha as string) || hoy, tipo: (d.tipo as string) || 'receptor',
      concepto: String(d.concepto ?? 'Gasto'), monto: Number(d.monto), proveedor: (d.proveedor as string) || null,
      numero_boleta: (d.numero_boleta as string) || null, estado: (d.estado as string) || 'por_rendir', rendicion_id: null,
      fecha_reembolso: null, observaciones: null, usuario_id: a.usuarioId, created_at: a.ahora() }
    j.gastos.push(g)
    return a.ok(vistaGasto(db, g), 201)
  }
  if (metodo === 'POST' && url === '/gastos/reembolsar') {
    const { gasto_ids, fecha } = a.cuerpo() as { gasto_ids: string[]; fecha?: string }
    const gastos = j.gastos.filter((g) => gasto_ids.includes(g.id))
    for (const g of gastos) { g.estado = 'reembolsado'; g.fecha_reembolso = fecha || hoy }
    for (const r of j.rendiciones) {
      if (r.estado === 'enviada' && !j.gastos.some((g) => g.rendicion_id === r.id && g.estado === 'rendido')
        && j.gastos.some((g) => g.rendicion_id === r.id)) { r.estado = 'pagada'; r.fecha_pago = fecha || hoy }
    }
    return a.ok(gastos.map((g) => vistaGasto(db, g)))
  }
  const vistaRendicion = (r: RendicionDemo, conGastos = false) => ({
    ...r, total: String(r.total), cliente_nombre: nombreCliente(db, r.cliente_id),
    cantidad: j.gastos.filter((g) => g.rendicion_id === r.id).length,
    ...(conGastos ? { gastos: j.gastos.filter((g) => g.rendicion_id === r.id).map((g) => vistaGasto(db, g)) } : {}),
  })
  if (metodo === 'GET' && url === '/gastos/rendiciones') {
    return a.ok(j.rendiciones.filter((r) => !params.cliente_id || r.cliente_id === params.cliente_id)
      .sort((x, y) => y.numero - x.numero).map((r) => vistaRendicion(r)))
  }
  if (metodo === 'POST' && url === '/gastos/rendiciones') {
    const { gasto_ids, observaciones } = a.cuerpo() as { gasto_ids: string[]; observaciones?: string }
    const gastos = j.gastos.filter((g) => gasto_ids.includes(g.id))
    if (gastos.some((g) => g.estado !== 'por_rendir')) return a.error(400, 'Solo se pueden rendir gastos que están por rendir.')
    if (new Set(gastos.map((g) => g.cliente_id)).size !== 1) return a.error(400, 'Una rendición es para un solo cliente.')
    const r: RendicionDemo = { id: a.uid(), numero: j.rendiciones.reduce((mx, x) => Math.max(mx, x.numero), 0) + 1,
      cliente_id: gastos[0].cliente_id, fecha: hoy, total: gastos.reduce((s, g) => s + g.monto, 0), estado: 'enviada',
      fecha_pago: null, observaciones: observaciones ?? null, created_at: a.ahora() }
    j.rendiciones.push(r)
    for (const g of gastos) { g.estado = 'rendido'; g.rendicion_id = r.id }
    return a.ok(vistaRendicion(r, true), 201)
  }
  if ((m = /^\/gastos\/rendiciones\/([^/]+)(\/[a-z]+)?$/.exec(url))) {
    const r = j.rendiciones.find((x) => x.id === m![1])
    if (!r) return a.error(404, 'Rendición no encontrada')
    if (metodo === 'GET') return a.ok(vistaRendicion(r, true))
    if (metodo === 'POST' && m[2] === '/pagada') {
      r.estado = 'pagada'; r.fecha_pago = hoy
      for (const g of j.gastos.filter((x) => x.rendicion_id === r.id && x.estado === 'rendido')) { g.estado = 'reembolsado'; g.fecha_reembolso = hoy }
      return a.ok(vistaRendicion(r, true))
    }
    if (metodo === 'POST' && m[2] === '/anular') {
      r.estado = 'anulada'
      for (const g of j.gastos.filter((x) => x.rendicion_id === r.id)) { g.estado = 'por_rendir'; g.rendicion_id = null }
      return a.ok(vistaRendicion(r, true))
    }
  }
  return a.error(501, 'Esta función del módulo judicial está disponible en la versión completa con servidor.')
}

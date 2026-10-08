/*
 * MODO DEMO: backend simulado dentro del navegador.
 *
 * Cuando la app se compila con `npm run build:demo`, este adaptador
 * reemplaza las llamadas HTTP de axios: los datos viven en localStorage
 * del navegador de quien mira la demo. Sirve para publicar SOLO el
 * frontend (ej. Vercel) y que se pueda "jugar" con datos de práctica
 * sin servidor ni base de datos.
 *
 * Replica las reglas de negocio clave del backend real:
 *  - solo el CAPITAL descuenta el saldo de la cobranza
 *  - cuotas → pagada / pagada_parcial; todas pagadas → acuerdo cumplido
 *  - gestiones automáticas (ACUERDO DE PAGO, ABONO, Pagado)
 *  - un solo acuerdo vigente por cobranza
 */

import type { AxiosAdapter, InternalAxiosRequestConfig, AxiosResponse } from 'axios'
import * as calc from './demoCalculos'

const CLAVE_DB = 'cartera_demo_db'
const VERSION_SEMILLA = 10
const UF_DEMO = '39841.72'
const CLAVE_SESION = 'cartera_demo_sesion'
const PLANTILLA_DEMO = 'Estimado(a) {deudor}:\n\nLe escribimos de {empresa} por la deuda N° {numero} con {cliente}, cuyo saldo a la fecha es de {saldo}.\n\nPuede pagar por transferencia a:\n{datos_pago}\n\nUna vez realizado el pago, envíenos el comprobante por este medio para registrarlo y dar por cerrada su cobranza.\n\nAtentamente,\n{empresa}'

// ---------- utilidades ----------

let secuencia = 1000
const uid = () => `demo-${++secuencia}-${Math.random().toString(36).slice(2, 8)}`
const ahora = () => new Date().toISOString()
const hoy = () => new Date().toISOString().slice(0, 10)

function clp(v: number): string {
  return '$' + Math.round(v).toLocaleString('es-CL')
}

// Catálogo fijo de roles (no cambia; no se guarda en localStorage).
const ROLES = [
  { id: 1, nombre: 'admin', descripcion: 'Acceso total y gestión de usuarios' },
  { id: 2, nombre: 'supervisor', descripcion: 'Ve todo, genera informes' },
  { id: 3, nombre: 'operador', descripcion: 'Gestiona sus cobranzas' },
  { id: 4, nombre: 'viewer', descripcion: 'Solo lectura' },
  { id: 5, nombre: 'abogado', descripcion: 'Causas judiciales, escritos y plazos' },
  { id: 6, nombre: 'procurador', descripcion: 'Actuaciones, notificaciones y plazos' },
  { id: 7, nombre: 'mandante', descripcion: 'Portal de clientes: ve solo su cartera' },
]

// En la demo la organización tiene el plan más completo.
const FUNCIONES_DEMO = [
  'cobranzas', 'deudores', 'gestiones', 'acuerdos', 'pagos', 'informes', 'carga_masiva',
  'documentos', 'campos_personalizados', 'agenda', 'mensaje_pago', 'judicial',
  'portal_mandantes', 'recordatorios', 'comunicaciones', 'calculadora_369',
  'envio_automatico', 'pagos_en_linea', 'api',
]

// Tipos de gestión de sistema, con el mismo código estable que el backend.
const TIPOS_SISTEMA: [string, string, string][] = [
  ['Llamada telefónica', 'llamada', 'contacto'], ['Email enviado', 'email', 'contacto'],
  ['WhatsApp', 'whatsapp', 'contacto'], ['Carta de cobranza', 'carta', 'contacto'],
  ['Acuerdo de pago', 'acuerdo', 'pago'], ['Visita en terreno', 'visita', 'contacto'],
  ['Nota interna', 'nota', 'otro'], ['Gestión automática', 'automatica', 'otro'],
  ['Cobranza ingresada al sistema', 'ingreso', 'otro'], ['Demanda presentada', 'demanda', 'judicial'],
  ['Pagaré ejecutado', 'documento_ejecutado', 'judicial'], ['Acuerdo incumplido', 'acuerdo_incumplido', 'negativo'],
  ['Abono', 'abono', 'pago'], ['Pagado', 'pagado', 'pago'], ['No contesta', 'no_contesta', 'contacto'],
  ['Promesa de pago', 'promesa_pago', 'pago'], ['Negativa de pago', 'negativa_pago', 'negativo'],
  ['SMS enviado', 'sms', 'contacto'],
]

// Quita la contraseña antes de devolver un usuario (nunca se expone) y
// agrega los campos que entrega el backend real.
function sinPassword<T extends { password?: string; rol_id: number; cliente_id: string | null }>(u: T) {
  const { password: _p, ...seguro } = u
  return {
    ...seguro,
    rol_nombre: ROLES.find((r) => r.id === u.rol_id)?.nombre ?? null,
    mfa_activo: false, debe_cambiar_password: false, bloqueado: false,
  }
}

function sumarMeses(fechaISO: string, meses: number): string {
  const [a, m, d] = fechaISO.split('-').map(Number)
  const totalMeses = (m - 1) + meses
  const anio = a + Math.floor(totalMeses / 12)
  const mes = (totalMeses % 12) + 1
  const ultimoDia = new Date(anio, mes, 0).getDate()
  const dia = Math.min(d, ultimoDia)
  const dd = String(dia).padStart(2, '0')
  const mm = String(mes).padStart(2, '0')
  return `${anio}-${mm}-${dd}`
}

// Dígito verificador de un RUT chileno (módulo 11) para que los datos de
// práctica tengan RUTs con formato válido.
function digitoVerificadorRut(cuerpo: number): string {
  let suma = 0
  let mult = 2
  for (let n = cuerpo; n > 0; n = Math.floor(n / 10)) {
    suma += (n % 10) * mult
    mult = mult === 7 ? 2 : mult + 1
  }
  const resto = 11 - (suma % 11)
  if (resto === 11) return '0'
  if (resto === 10) return 'K'
  return String(resto)
}

function sinAcentos(s: string): string {
  return s.normalize('NFD').replace(/[̀-ͯ]/g, '')
}

// Genera N deudores + sus cobranzas ficticias en la filial Costa (id 7)
// del cliente cl-1. Todo inventado y determinístico (mismo resultado en
// cada reseed): sirve para poblar la demo sin usar datos reales.
function generarCasosDemo(cantidad: number, numeroInicial: number) {
  const nombres = ['José', 'María', 'Juan', 'Ana', 'Luis', 'Carmen', 'Pedro', 'Rosa', 'Carlos', 'Javiera', 'Diego', 'Fernanda', 'Matías', 'Camila', 'Sebastián', 'Valentina', 'Francisco', 'Antonia', 'Cristóbal', 'Catalina', 'Felipe', 'Isidora', 'Benjamín', 'Martina', 'Vicente']
  const apellidos = ['González', 'Muñoz', 'Rojas', 'Díaz', 'Pérez', 'Soto', 'Contreras', 'Silva', 'Martínez', 'Sepúlveda', 'Morales', 'Rodríguez', 'López', 'Fuentes', 'Hernández', 'Torres', 'Araya', 'Flores', 'Espinoza', 'Castillo', 'Tapia', 'Reyes', 'Gutiérrez', 'Vergara', 'Cortés']
  const comunas = ['Santiago', 'Maipú', 'Puente Alto', 'La Florida', 'Las Condes', 'Ñuñoa', 'Providencia', 'San Bernardo', 'Conchalí', 'Recoleta', 'Peñalolén', 'La Pintana', 'Quilicura', 'Renca', 'Estación Central', 'Lo Espejo']
  const tiposDoc = ['pagare', 'pagare', 'pagare', 'factura', 'letra']

  const deudores = []
  const cobranzas = []

  for (let i = 0; i < cantidad; i++) {
    const nombrePila = nombres[i % nombres.length]
    const ap1 = apellidos[(i * 3) % apellidos.length]
    const ap2 = apellidos[(i * 7 + 4) % apellidos.length]
    const cuerpoRut = 9000000 + i * 53171
    const rut = `${cuerpoRut}-${digitoVerificadorRut(cuerpoRut)}`
    const comuna = comunas[i % comunas.length]
    const idDeudor = `d-s${i + 1}`
    const usuario = sinAcentos(`${nombrePila}.${ap1}${i + 1}`).toLowerCase()
    const cel = `+56 9 ${String(6000 + i).padStart(4, '0')} ${String(1000 + (i * 37) % 8999).padStart(4, '0')}`

    deudores.push({
      id: idDeudor, rut, tipo: 'natural', nombre: `${nombrePila} ${ap1} ${ap2}`,
      comuna, ciudad: 'Santiago', en_boletin_comercial: i % 3 === 0, datos_extra: {},
      observaciones: null as string | null,
      contactos: [
        { id: `ct-s${i + 1}a`, deudor_id: idDeudor, tipo: 'celular', valor: cel, activo: true },
        { id: `ct-s${i + 1}b`, deudor_id: idDeudor, tipo: 'email', valor: `${usuario}@correo.cl`, activo: true },
      ],
    })

    const monto = 150000 + ((i * 17) % 60) * 25000
    const pagada = i % 6 === 5
    const tipoDoc = tiposDoc[i % tiposDoc.length]
    const mm = String((i % 6) + 1).padStart(2, '0')
    const dd = String((i % 27) + 1).padStart(2, '0')

    cobranzas.push({
      id: `cob-s${i + 1}`, numero: numeroInicial + i,
      cliente_id: 'cl-1', filial_id: 7 as number | null, deudor_id: idDeudor,
      id_externo: String(360000 + i * 7),
      monto_original: String(monto), monto_actual: pagada ? '0' : String(monto),
      tipo_documento: tipoDoc,
      numero_documento: tipoDoc === 'pagare' ? `PG-2026-${String(1000 + i)}` : null,
      fecha_vencimiento_documento: null as string | null,
      datos_extra: (i % 2 === 0 ? { prevision: 'FONASA' } : {}) as Record<string, string>,
      terceros: [] as { tercero_id: string; rol: string; nombre: string; rut: string | null }[],
      estado: pagada ? 'pagada' : 'activa', tipo: 'extrajudicial',
      fecha_ingreso: `2026-${mm}-${dd}`,
      observaciones: null as string | null,
    })
  }

  return { deudores, cobranzas }
}

// ---------- datos de práctica (semilla) ----------

function semilla() {
  const usuarios = [
    { id: 'u-admin', nombre: 'Administrador', email: 'admin@demo.cl', password: 'demo1234', rol_id: 1, activo: true, cliente_id: null as string | null },
    { id: 'u-supervisor', nombre: 'Ana Torres', email: 'ana@demo.cl', password: 'demo1234', rol_id: 2, activo: true, cliente_id: null },
    { id: 'u-operador', nombre: 'María Soto', email: 'maria@demo.cl', password: 'demo1234', rol_id: 3, activo: true, cliente_id: null },
    // Usuario del portal de clientes: ve solo la cartera de Clínica Los Andes.
    { id: 'u-mandante', nombre: 'Paula Rivas', email: 'cliente@demo.cl', password: 'demo1234', rol_id: 7, activo: true, cliente_id: 'cl-1' },
  ]
  const clientes = [
    { id: 'cl-1', rut: '96570220-7', razon_social: 'CLÍNICA LOS ANDES S.A.', nombre_fantasia: 'Clínica Los Andes' },
    { id: 'cl-2', rut: '99520000-1', razon_social: 'COMERCIAL DEL SUR SPA', nombre_fantasia: 'Comercial Sur' },
  ]
  const filiales = [
    ...['Casa Matriz', 'Norte', 'Centro', 'Sur', 'Oriente', 'Poniente', 'Costa', 'Cordillera', 'Valle']
      .map((nombre, i) => ({ id: i + 1, cliente_id: 'cl-1', nombre, activo: true })),
    { id: 10, cliente_id: 'cl-2', nombre: 'Principal', activo: true },
  ]
  const deudores = [
    {
      id: 'd-1', rut: '12345678-5', tipo: 'natural', nombre: 'Pedro Antonio González Rojas',
      comuna: 'Valparaíso', ciudad: 'Valparaíso', en_boletin_comercial: true, datos_extra: {},
      observaciones: 'Deudor del caso de práctica. Padre de la paciente.',
      contactos: [
        { id: 'ct-1', deudor_id: 'd-1', tipo: 'celular', valor: '+56 9 5678 1234', activo: true },
        { id: 'ct-2', deudor_id: 'd-1', tipo: 'email', valor: 'pedro.gonzalez@gmail.com', activo: true },
      ],
    },
    {
      id: 'd-2', rut: '15987654-3', tipo: 'natural', nombre: 'María Pérez Soto',
      comuna: 'Viña del Mar', ciudad: 'Viña del Mar', en_boletin_comercial: false, datos_extra: {}, observaciones: null,
      contactos: [
        { id: 'ct-3', deudor_id: 'd-2', tipo: 'celular', valor: '+56 9 4433 2211', activo: true },
      ],
    },
  ]
  const cobranzas = [
    {
      id: 'cob-1', numero: 20001, cliente_id: 'cl-1', filial_id: 3 as number | null, deudor_id: 'd-1',
      id_externo: '145678', monto_original: '850000', monto_actual: '705000',
      tipo_documento: 'pagare', numero_documento: 'PG-2025-0145',
      fecha_vencimiento_documento: '2026-05-31' as string | null,
      datos_extra: { prevision: 'ISAPRE' } as Record<string, string>,
      terceros: [{ tercero_id: 't-1', rol: 'paciente', nombre: 'Josefa González Pérez', rut: '25123456-K' as string | null }],
      estado: 'acuerdo_pago', tipo: 'extrajudicial',
      fecha_ingreso: '2026-06-02',
      observaciones: 'Caso ingresado vía planilla mensual del cliente. Paciente menor de edad atendida por urgencia.',
    },
    {
      id: 'cob-2', numero: 20002, cliente_id: 'cl-1', filial_id: 3, deudor_id: 'd-2',
      id_externo: '198765', monto_original: '420000', monto_actual: '420000',
      tipo_documento: 'pagare', numero_documento: null,
      fecha_vencimiento_documento: null, datos_extra: {}, terceros: [],
      estado: 'activa', tipo: 'extrajudicial',
      fecha_ingreso: '2026-06-08', observaciones: null,
    },
    {
      id: 'cob-3', numero: 20003, cliente_id: 'cl-2', filial_id: 10, deudor_id: 'd-2',
      id_externo: 'SAP-77120', monto_original: '1250000', monto_actual: '1250000',
      tipo_documento: 'factura', numero_documento: 'F-00981',
      fecha_vencimiento_documento: '2026-04-30', datos_extra: {}, terceros: [],
      estado: 'activa', tipo: 'extrajudicial',
      fecha_ingreso: '2026-06-08', observaciones: null,
    },
  ]
  const tiposGestion = TIPOS_SISTEMA.map(([nombre, codigo, categoria], i) => ({
    id: i + 1, nombre, codigo: codigo as string | null, categoria, activo: true, propio: false,
  }))

  // Campo personalizado de ejemplo: la previsión solo aplica a la clínica.
  const campos = [
    {
      id: 'campo-1', entidad: 'cobranza', clave: 'prevision', etiqueta: 'Previsión',
      tipo: 'seleccion', opciones: ['FONASA', 'ISAPRE', 'Particular'], cliente_id: 'cl-1' as string | null,
      obligatorio: false, orden: 10, activo: true,
    },
  ]
  const etiquetas: Record<string, string> = {}

  const gestiones = [
    {
      id: 'g-1', cobranza_id: 'cob-1', usuario_id: 'u-operador', tipo_id: 1 as number | null,
      descripcion: 'Primera llamada a don Pedro. Contesta. Reconoce la deuda y pide unos días para revisar su situación.',
      fecha_gestion: '2026-06-02T10:30:00', fecha_proximo_contacto: null,
    },
    {
      id: 'g-2', cobranza_id: 'cob-1', usuario_id: 'u-operador', tipo_id: 4,
      descripcion: 'Se envía carta de cobranza formal por correo certificado. Comprobante Correos Chile N° 458921.',
      fecha_gestion: '2026-06-05T15:00:00', fecha_proximo_contacto: null,
    },
    {
      id: 'g-3', cobranza_id: 'cob-1', usuario_id: 'u-operador', tipo_id: 5,
      descripcion: 'ACUERDO DE PAGO: $870.000 en 6 cuota(s) de $145.000. Primera cuota vence el 11-07-2026, última el 11-12-2026.',
      fecha_gestion: '2026-06-11T11:45:00', fecha_proximo_contacto: null,
    },
  ]
  const cuotas = Array.from({ length: 6 }, (_, i) => ({
    id: `cu-${i + 1}`, acuerdo_id: 'ac-1', numero_cuota: i + 1, monto: '145000',
    fecha_vencimiento: sumarMeses('2026-07-11', i),
    monto_pagado: i === 0 ? '145000' : '0',
    estado: i === 0 ? 'pagada' : 'pendiente',
  }))
  const acuerdos = [
    {
      id: 'ac-1', cobranza_id: 'cob-1', estado: 'vigente', fecha_acuerdo: '2026-06-11',
      fecha_termino: '2026-12-11', pie: '0', monto_total_acordado: '870000',
      numero_cuotas: 6, dia_pago: 11, fecha_primera_cuota: '2026-07-11',
      usuario_id: 'u-operador', cuotas, firma_cliente: 'sin_firmar', observaciones: null as string | null,
    },
  ]
  const historicos = Array.from({ length: 9 }, (_, i) => {
    const d = new Date(); d.setDate(10); d.setMonth(d.getMonth() - (i + 1))
    const capital = 180000 + ((i * 37) % 7) * 45000
    return {
      id: `p-h${i}`, cobranza_id: `cob-s${i * 3 + 1}`, cuota_id: null as string | null,
      fecha_pago: d.toISOString().slice(0, 10), monto: String(Math.round(capital * 1.08)),
      capital: String(capital), honorarios: String(Math.round(capital * 0.08)), intereses: '0',
      gastos_judiciales: '0', forma_pago: 'transferencia', numero_comprobante: null as string | null,
      estado_pago: 'abono', usuario_id: 'u-operador',
    }
  })
  const pagos = [
    ...historicos,
    {
      id: 'p-1', cobranza_id: 'cob-1', cuota_id: 'cu-1' as string | null, fecha_pago: '2026-07-12',
      monto: '145000', capital: '123750', honorarios: '21250',
      intereses: '0', gastos_judiciales: '0',
      forma_pago: 'transferencia', numero_comprobante: 'BCI-20260712-458912' as string | null,
      estado_pago: 'cuota', usuario_id: 'u-operador',
    },
  ]

  // 100 casos ficticios extra en la filial Costa del cliente 1, para que la
  // demo tenga volumen realista. Se anexan a los 3 casos guiados de arriba.
  const casosDemo = generarCasosDemo(100, 20004)
  deudores.push(...(casosDemo.deudores as never[]))
  cobranzas.push(...(casosDemo.cobranzas as never[]))

  // Datos de la empresa que "usa" el sistema en la demo. En la versión
  // completa se editan desde Configuración → Mi empresa.
  const empresa = {
    razon_social: 'Mi Empresa de Cobranza SpA',
    nombre_fantasia: 'Mi Empresa',
    rut: '76123456-7',
    wordmark: 'MI EMPRESA DE COBRANZA',
    bajada: 'GESTIÓN Y RECUPERO DE CARTERA',
    firma_documentos: 'Mi Empresa de Cobranza SpA',
    direccion: 'Av. Siempre Viva 1234, oficina 56',
    ciudad: 'Santiago, Chile',
    horario_atencion: 'Atención de 9 a 18 hrs.',
    telefonos: '(2) 2345 6789',
    emails: 'contacto@miempresa.cl',
    sitio_web: 'www.miempresa.cl',
    instrucciones_pago: [
      'Transferencia electrónica a la cuenta del cliente.',
      'Pago presencial en nuestras oficinas.',
    ].join('\n'),
    updated_at: ahora(),
  }

  // Agenda de ejemplo: un recordatorio para hoy y compromisos en las gestiones.
  const recordatorios = [
    { id: 'rec-1', usuario_id: 'u-admin', cobranza_id: 'cob-2' as string | null, fecha: hoy(), hora: '10:30' as string | null,
      titulo: 'Llamar a María Pérez para confirmar la transferencia', nota: null as string | null,
      estado: 'pendiente', creado_por: 'u-admin', created_at: ahora() },
  ]
  gestiones.push({
    id: 'g-4', cobranza_id: 'cob-3', usuario_id: 'u-admin', tipo_id: 16,
    descripcion: 'Se compromete a pagar la mitad esta semana.',
    fecha_gestion: ahora(), fecha_proximo_contacto: sumarMeses(hoy(), 0) as never,
  })
  const plantilla = ''
  const cobro = { pct_judicial: '10', comision_pct: '2.2491' }

  return { version: VERSION_SEMILLA, empresa, usuarios, clientes, filiales, deudores, cobranzas, tiposGestion, campos, etiquetas, recordatorios, plantilla, cobro, gestiones, acuerdos, pagos, proximoNumero: 20004 + casosDemo.cobranzas.length }
}

// ---------- base de datos en localStorage ----------

type DB = ReturnType<typeof semilla>

function cargarDB(): DB {
  try {
    const crudo = localStorage.getItem(CLAVE_DB)
    if (crudo) {
      const db = JSON.parse(crudo)
      if (db.version === VERSION_SEMILLA) return db
    }
  } catch { /* semilla nueva */ }
  const db = semilla()
  guardarDB(db)
  return db
}

function guardarDB(db: DB) {
  localStorage.setItem(CLAVE_DB, JSON.stringify(db))
}

// ---------- helpers de respuesta ----------

function ok(config: InternalAxiosRequestConfig, data: unknown, status = 200, headers: Record<string, string> = {}): AxiosResponse {
  return { data, status, statusText: 'OK', headers, config }
}

function error(status: number, detail: string) {
  return Promise.reject({
    isAxiosError: true,
    response: { status, data: { detail } },
    message: detail,
  })
}

function cuerpo(config: InternalAxiosRequestConfig): Record<string, unknown> {
  const d = config.data
  if (!d) return {}
  if (typeof d === 'string') {
    try { return JSON.parse(d) } catch { /* form-urlencoded */ }
    return Object.fromEntries(new URLSearchParams(d))
  }
  return d as Record<string, unknown>
}

function usuarioDelToken(config: InternalAxiosRequestConfig, db: DB) {
  const auth = String(config.headers?.Authorization ?? '')
  const id = auth.replace('Bearer demo-token-', '')
  return db.usuarios.find((u) => u.id === id) ?? db.usuarios[0]
}

function gestionAutomatica(db: DB, cobranza_id: string, usuario_id: string, codigoTipo: string, descripcion: string) {
  const tipo = db.tiposGestion.find((t) => t.codigo === codigoTipo)
  db.gestiones.push({
    id: uid(), cobranza_id, usuario_id, tipo_id: tipo?.id ?? null,
    descripcion, fecha_gestion: ahora(), fecha_proximo_contacto: null,
  })
}

// ---------- el adaptador ----------

export const adaptadorDemo: AxiosAdapter = async (config) => {
  const metodo = (config.method ?? 'get').toUpperCase()
  const url = (config.url ?? '').split('?')[0]
  const params = (config.params ?? {}) as Record<string, string>
  const db = cargarDB()

  // pequeña pausa para que se sienta real
  await new Promise((r) => setTimeout(r, 120))

  // ---- auth ----
  // La "cookie de sesión" de la demo es una marca en sessionStorage.
  const usuarioActual = (u: DB['usuarios'][number]) => ({
    id: u.id, nombre: u.nombre, email: u.email, rol_id: u.rol_id,
    rol: ROLES.find((r) => r.id === u.rol_id)?.nombre ?? 'operador',
    cliente_id: u.cliente_id, mfa_activo: false, debe_cambiar_password: false,
    organizacion: {
      id: 'org-demo', nombre: db.empresa.nombre_fantasia ?? 'Organización demo', plan: 'premium',
      estado: 'activa', funciones: FUNCIONES_DEMO, etiquetas: db.etiquetas,
    },
  })
  const respuestaToken = (u: DB['usuarios'][number]) => ({
    access_token: `demo-token-${u.id}`, token_type: 'bearer', expira_en: 900, usuario: usuarioActual(u),
  })
  if (metodo === 'POST' && url === '/auth/login') {
    const { email, password } = cuerpo(config) as { email: string; password: string }
    const u = db.usuarios.find((x) => x.email === email && x.password === password)
    if (!u || !u.activo) return error(401, 'Email o contraseña incorrectos')
    try { sessionStorage.setItem(CLAVE_SESION, u.id) } catch { /* modo privado */ }
    return ok(config, respuestaToken(u))
  }
  if (metodo === 'POST' && url === '/auth/refresh') {
    let id: string | null = null
    try { id = sessionStorage.getItem(CLAVE_SESION) } catch { /* modo privado */ }
    const u = db.usuarios.find((x) => x.id === id)
    return u ? ok(config, respuestaToken(u)) : error(401, 'Sin sesión.')
  }
  if (metodo === 'POST' && url === '/auth/logout') {
    try { sessionStorage.removeItem(CLAVE_SESION) } catch { /* modo privado */ }
    return ok(config, null, 204)
  }
  if (metodo === 'GET' && url === '/auth/me') return ok(config, usuarioActual(usuarioDelToken(config, db)))
  if (metodo === 'PUT' && url === '/auth/cambiar-password') {
    const u = usuarioDelToken(config, db)
    const datos = cuerpo(config) as { password_actual: string; password_nueva: string }
    if (datos.password_actual !== u.password) return error(401, 'La contraseña actual no es correcta')
    if (datos.password_nueva.length < 12) return error(422, 'La contraseña debe tener al menos 12 caracteres.')
    u.password = datos.password_nueva
    guardarDB(db)
    return ok(config, null, 204)
  }

  // ---- configuración de la organización ----
  const vistaOrg = () => ({ id: 'org-demo', nombre: db.empresa.nombre_fantasia, slug: 'demo', plan: 'premium',
    estado: 'activa', funciones: FUNCIONES_DEMO, etiquetas: db.etiquetas,
    plantilla_mensaje_pago: db.plantilla || PLANTILLA_DEMO, cobro: db.cobro })
  if (metodo === 'GET' && url === '/organizacion') return ok(config, vistaOrg())
  if (metodo === 'PUT' && url === '/organizacion') {
    const datos = cuerpo(config) as { nombre?: string; etiquetas?: Record<string, string>;
      plantilla_mensaje_pago?: string; cobro?: { pct_judicial: string; comision_pct: string } }
    if (datos.etiquetas) db.etiquetas = Object.fromEntries(Object.entries(datos.etiquetas).filter(([, v]) => v))
    if (datos.nombre) db.empresa.nombre_fantasia = datos.nombre
    if (datos.plantilla_mensaje_pago !== undefined) db.plantilla = datos.plantilla_mensaje_pago
    if (datos.cobro) db.cobro = datos.cobro
    guardarDB(db)
    return ok(config, vistaOrg())
  }

  // ---- agenda, recordatorios, UF, calculadora, mensaje de pago ----
  if (metodo === 'GET' && (url === '/agenda' || url === '/agenda/hoy')) {
    const hoyIso = hoy()
    const desde = url === '/agenda/hoy' ? new Date(Date.now() - 60 * 86400000).toISOString().slice(0, 10) : (params.desde ?? hoyIso.slice(0, 8) + '01')
    const hasta = url === '/agenda/hoy' ? hoyIso : (params.hasta ?? sumarMeses(hoyIso, 1))
    const items: Record<string, unknown>[] = []
    const enRango = (f: string) => f >= desde && f <= hasta
    for (const c of db.cobranzas) {
      if (!['activa', 'acuerdo_pago', 'judicial'].includes(c.estado)) continue
      const ultima = db.gestiones.filter((g) => g.cobranza_id === c.id)
        .sort((a, b) => b.fecha_gestion.localeCompare(a.fecha_gestion))[0]
      const f = ultima?.fecha_proximo_contacto as string | null | undefined
      if (!f || !enRango(f)) continue
      const d = db.deudores.find((x) => x.id === c.deudor_id)
      const promesa = db.tiposGestion.find((t) => t.id === ultima.tipo_id)?.codigo === 'promesa_pago'
      items.push({ tipo: promesa ? 'promesa' : 'contacto', fecha: f, hora: null,
        titulo: promesa ? `Promesa de pago: ${d?.nombre}` : `Contactar a ${d?.nombre}`,
        detalle: ultima.descripcion, atrasado: f < hoyIso, cobranza_id: c.id, numero_cobranza: c.numero,
        deudor: d?.nombre, monto: Number(c.monto_actual), responsable_id: ultima.usuario_id,
        recordatorio_id: null, cuota_id: null })
    }
    for (const a of db.acuerdos.filter((x) => x.estado === 'vigente')) {
      const c = db.cobranzas.find((x) => x.id === a.cobranza_id)
      const d = db.deudores.find((x) => x.id === c?.deudor_id)
      for (const cu of a.cuotas) {
        if (cu.estado === 'pagada' || !enRango(cu.fecha_vencimiento)) continue
        const saldo = Number(cu.monto) - Number(cu.monto_pagado)
        items.push({ tipo: 'cuota', fecha: cu.fecha_vencimiento, hora: null,
          titulo: `Cuota ${cu.numero_cuota}/${a.numero_cuotas}: ${d?.nombre}`, detalle: `Por pagar ${clp(saldo)}`,
          atrasado: cu.fecha_vencimiento < hoyIso, cobranza_id: c?.id, numero_cobranza: c?.numero, deudor: d?.nombre,
          monto: saldo, responsable_id: a.usuario_id, recordatorio_id: null, cuota_id: cu.id })
      }
    }
    for (const r of db.recordatorios.filter((x) => x.estado === 'pendiente' && enRango(x.fecha))) {
      const c = db.cobranzas.find((x) => x.id === r.cobranza_id)
      items.push({ tipo: 'recordatorio', fecha: r.fecha, hora: r.hora, titulo: r.titulo, detalle: r.nota,
        atrasado: r.fecha < hoyIso, cobranza_id: r.cobranza_id, numero_cobranza: c?.numero ?? null,
        deudor: null, monto: null, responsable_id: r.usuario_id, recordatorio_id: r.id, cuota_id: null })
    }
    items.sort((a, b) => String(a.fecha).localeCompare(String(b.fecha)))
    return ok(config, items)
  }
  if (metodo === 'GET' && url === '/recordatorios') {
    return ok(config, db.recordatorios.filter((r) =>
      (!params.cobranza_id || r.cobranza_id === params.cobranza_id) && r.estado === 'pendiente'))
  }
  if (metodo === 'POST' && url === '/recordatorios') {
    const datos = cuerpo(config) as Record<string, string | null>
    const u = usuarioDelToken(config, db)
    const nuevo = { id: uid(), usuario_id: u.id, cobranza_id: datos.cobranza_id ?? null, fecha: String(datos.fecha),
      hora: datos.hora ?? null, titulo: String(datos.titulo), nota: datos.nota ?? null, estado: 'pendiente',
      creado_por: u.id, created_at: ahora() }
    db.recordatorios.push(nuevo)
    guardarDB(db)
    return ok(config, nuevo, 201)
  }
  if (metodo === 'PUT' && /^\/recordatorios\/[^/]+$/.test(url)) {
    const r = db.recordatorios.find((x) => x.id === url.split('/')[2])
    if (!r) return error(404, 'Recordatorio no encontrado')
    Object.assign(r, cuerpo(config))
    guardarDB(db)
    return ok(config, r)
  }
  if (metodo === 'GET' && url === '/indicadores/uf') {
    return ok(config, { fecha: hoy(), valor: UF_DEMO, fuente: 'demo' })
  }
  if (metodo === 'POST' && url.startsWith('/calculadora/')) {
    const d = cuerpo(config) as Record<string, unknown>
    const pct = Number(db.cobro.pct_judicial)
    try {
      if (url === '/calculadora/honorarios') {
        return ok(config, calc.aTexto(calc.honorarios(Number(d.capital), d.uf ? Number(d.uf) : null, String(d.modalidad), pct)))
      }
      if (url === '/calculadora/abono') {
        const h = calc.aTexto(calc.capitalDesdeAbono(Number(d.abono), d.uf ? Number(d.uf) : null, String(d.modalidad), pct))
        const abono = Math.round(Number(d.abono))
        return ok(config, { ...h, total_honorarios: String(abono - Number(h.capital)), total_deuda: String(abono) })
      }
      const plan = calc.acuerdo(d)
      if (url === '/calculadora/acuerdo') return ok(config, plan)
      if (url === '/calculadora/acuerdo/crear') {
        const cob = db.cobranzas.find((c) => c.id === d.cobranza_id)
        if (!cob) return error(404, 'Cobranza no encontrada')
        if (db.acuerdos.some((a) => a.cobranza_id === cob.id && a.estado === 'vigente')) {
          return error(400, 'La cobranza ya tiene un acuerdo vigente.')
        }
        const u = usuarioDelToken(config, db)
        const acuerdoId = uid()
        const nuevo = {
          id: acuerdoId, cobranza_id: cob.id, estado: 'vigente', fecha_acuerdo: hoy(),
          fecha_termino: plan.cuotas[plan.cuotas.length - 1].fecha, pie: plan.abono_inicial,
          monto_total_acordado: plan.gran_total, numero_cuotas: plan.numero_cuotas, dia_pago: null,
          fecha_primera_cuota: String(d.fecha_primera_cuota), usuario_id: u.id, firma_cliente: 'sin_firmar', observaciones: null,
          cuotas: plan.cuotas.map((f) => ({ id: uid(), acuerdo_id: acuerdoId, numero_cuota: f.numero, monto: f.total,
            fecha_vencimiento: String(f.fecha), monto_pagado: '0', estado: 'pendiente', capital: f.capital,
            intereses: f.intereses, honorarios: f.honorarios, gastos_judiciales: f.gastos_judiciales, comision: f.comision })),
        }
        db.acuerdos.push(nuevo as never)
        cob.estado = 'acuerdo_pago'
        gestionAutomatica(db, cob.id, u.id, 'acuerdo', `ACUERDO DE PAGO: ${plan.texto}`)
        guardarDB(db)
        return ok(config, nuevo, 201)
      }
    } catch (e) {
      return error(422, (e as Error).message)
    }
  }
  if (metodo === 'GET' && /^\/cobranzas\/[^/]+\/mensaje-pago$/.test(url)) {
    const c = db.cobranzas.find((x) => x.id === url.split('/')[2])
    if (!c) return error(404, 'Cobranza no encontrada')
    const d = db.deudores.find((x) => x.id === c.deudor_id)
    const cl = db.clientes.find((x) => x.id === c.cliente_id) as { instrucciones_pago?: string | null; nombre_fantasia: string; razon_social: string } | undefined
    const datosPago = (cl?.instrucciones_pago || db.empresa.instrucciones_pago || '').trim()
    const valores: Record<string, string> = {
      deudor: d?.nombre ?? '', nombre: (d?.nombre ?? '').split(' ')[0], saldo: clp(Number(c.monto_actual)),
      numero: String(c.numero), id_externo: c.id_externo ?? '', cliente: cl?.nombre_fantasia ?? cl?.razon_social ?? '',
      empresa: db.empresa.nombre_fantasia ?? db.empresa.razon_social, datos_pago: datosPago,
      telefono_empresa: db.empresa.telefonos ?? '', email_empresa: db.empresa.emails ?? '',
    }
    const texto = (db.plantilla || PLANTILLA_DEMO).replace(/\{(\w+)\}/g, (m, k) => valores[k] ?? m)
    const tel = d?.contactos.find((x) => x.activo && ['whatsapp', 'celular', 'telefono'].includes(x.tipo))?.valor ?? null
    const email = d?.contactos.find((x) => x.activo && x.tipo === 'email')?.valor ?? null
    const digitos = (tel ?? '').replace(/\D/g, '')
    const numero = digitos.length === 9 ? '56' + digitos : digitos
    const asunto = `Cobranza N° ${c.numero} - ${valores.cliente}`
    return ok(config, {
      texto, asunto, telefono: tel, email,
      whatsapp_url: `https://wa.me/${numero}?text=${encodeURIComponent(texto)}`,
      mailto_url: `mailto:${email ?? ''}?subject=${encodeURIComponent(asunto)}&body=${encodeURIComponent(texto)}`,
      falta_datos_pago: !datosPago,
    })
  }

  // ---- clientes y filiales (edición) ----
  if (metodo === 'POST' && url === '/clientes/') {
    const datos = cuerpo(config) as Record<string, string | null>
    const nuevo = { id: uid(), activo: true, ...datos }
    db.clientes.push(nuevo as never)
    guardarDB(db)
    return ok(config, nuevo, 201)
  }
  if (metodo === 'PUT' && /^\/clientes\/[^/]+$/.test(url)) {
    const c = db.clientes.find((x) => x.id === url.split('/')[2])
    if (!c) return error(404, 'Cliente no encontrado')
    Object.assign(c, cuerpo(config))
    guardarDB(db)
    return ok(config, c)
  }
  if (metodo === 'POST' && url === '/filiales/') {
    const datos = cuerpo(config) as { cliente_id: string; nombre: string }
    const nueva = { id: Math.max(...db.filiales.map((f) => f.id)) + 1, cliente_id: datos.cliente_id, nombre: datos.nombre, activo: true }
    db.filiales.push(nueva)
    guardarDB(db)
    return ok(config, nueva, 201)
  }
  if (metodo === 'PUT' && /^\/filiales\/\d+$/.test(url)) {
    const f = db.filiales.find((x) => x.id === Number(url.split('/')[2]))
    if (!f) return error(404, 'Filial no encontrada')
    Object.assign(f, cuerpo(config))
    guardarDB(db)
    return ok(config, f)
  }
  if (metodo === 'GET' && url === '/campos') {
    let lista = db.campos
    if (params.entidad) lista = lista.filter((c) => c.entidad === params.entidad)
    if (params.cliente_id) lista = lista.filter((c) => !c.cliente_id || c.cliente_id === params.cliente_id)
    if (!params.incluir_inactivos) lista = lista.filter((c) => c.activo)
    return ok(config, lista)
  }
  if (metodo === 'POST' && url === '/campos') {
    const datos = cuerpo(config) as Record<string, unknown> & { etiqueta: string }
    const clave = sinAcentos(datos.etiqueta).toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '')
    if (db.campos.some((c) => c.clave === clave && c.entidad === datos.entidad)) {
      return error(400, `Ya existe un campo con la clave '${clave}'.`)
    }
    const nuevo = { id: uid(), clave, activo: true, opciones: [], cliente_id: null, obligatorio: false, orden: 0, tipo: 'texto', entidad: 'cobranza', ...datos }
    db.campos.push(nuevo as never)
    guardarDB(db)
    return ok(config, nuevo, 201)
  }
  if (metodo === 'PUT' && /^\/campos\/[^/]+$/.test(url)) {
    const c = db.campos.find((x) => x.id === url.split('/')[2])
    if (!c) return error(404, 'Campo no encontrado')
    Object.assign(c, cuerpo(config))
    guardarDB(db)
    return ok(config, c)
  }

  // ---- mi empresa ----
  if (metodo === 'GET' && url === '/empresa') return ok(config, db.empresa)
  if (metodo === 'PUT' && url === '/empresa') {
    const u = usuarioDelToken(config, db)
    if (u.rol_id !== 1) return error(403, 'Se requiere rol de administrador para esta operación')
    db.empresa = { ...db.empresa, ...(cuerpo(config) as Record<string, unknown>), updated_at: ahora() } as typeof db.empresa
    guardarDB(db)
    return ok(config, db.empresa)
  }

  // ---- catálogos ----
  if (metodo === 'GET' && url === '/clientes/') {
    return ok(config, db.clientes.filter((c) => params.solo_activos === 'false' || (c as { activo?: boolean }).activo !== false))
  }
  if (metodo === 'GET' && url === '/filiales/') {
    const lista = db.filiales.filter((f) => (!params.cliente_id || f.cliente_id === params.cliente_id)
      && (params.solo_activas === 'false' || f.activo))
    return ok(config, lista)
  }
  if (metodo === 'GET' && url === '/gestiones/tipos') {
    return ok(config, params.solo_activos === 'false' ? db.tiposGestion : db.tiposGestion.filter((t) => t.activo))
  }
  if (metodo === 'POST' && url === '/gestiones/tipos') {
    const datos = cuerpo(config) as { nombre: string; categoria: string }
    const nuevo = { id: db.tiposGestion.length + 100, nombre: datos.nombre, codigo: null, categoria: datos.categoria, activo: true, propio: true }
    db.tiposGestion.push(nuevo)
    guardarDB(db)
    return ok(config, nuevo, 201)
  }
  if (metodo === 'PUT' && /^\/gestiones\/tipos\/\d+$/.test(url)) {
    const tipo = db.tiposGestion.find((x) => x.id === Number(url.split('/')[3]))
    if (!tipo || !tipo.propio) return error(404, 'Tipo no encontrado o es de sistema.')
    Object.assign(tipo, cuerpo(config))
    guardarDB(db)
    return ok(config, tipo)
  }

  // ---- usuarios (solo admin) ----
  if (metodo === 'GET' && url === '/usuarios/roles') return ok(config, ROLES)
  if (metodo === 'GET' && url === '/usuarios/') {
    return ok(config, db.usuarios.map(sinPassword).sort((a, b) => a.nombre.localeCompare(b.nombre)))
  }
  if (metodo === 'POST' && url === '/usuarios/') {
    const datos = cuerpo(config) as { nombre: string; email: string; password: string | null; rol_id: number;
      cliente_id?: string | null }
    if (db.usuarios.some((u) => u.email === datos.email)) {
      return error(400, 'Ese email ya está registrado.')
    }
    const nuevo = {
      id: uid(), nombre: datos.nombre, email: datos.email,
      password: datos.password ?? 'demo1234', rol_id: Number(datos.rol_id), activo: true,
      cliente_id: datos.cliente_id ?? null,
    }
    db.usuarios.push(nuevo)
    guardarDB(db)
    // En la demo no se envían correos: el usuario nuevo entra con demo1234.
    return ok(config, sinPassword(nuevo), 201, { 'x-invitacion-enviada': '0' })
  }
  if (metodo === 'POST' && /^\/usuarios\/[^/]+\/(invitar|desbloquear|reiniciar-2fa)$/.test(url)) {
    if (url.endsWith('/invitar')) return error(503, 'La demo no envía correos. Los usuarios creados acá entran con la clave demo1234.')
    return ok(config, null, 204)
  }
  if (metodo === 'PUT' && /^\/usuarios\/[^/]+\/password$/.test(url)) {
    const id = url.split('/')[2]
    const u = db.usuarios.find((x) => x.id === id)
    if (!u) return error(404, 'Usuario no encontrado')
    u.password = (cuerpo(config) as { password_nueva: string }).password_nueva
    guardarDB(db)
    return ok(config, null, 204)
  }
  if (metodo === 'PUT' && /^\/usuarios\/[^/]+$/.test(url)) {
    const id = url.split('/')[2]
    const u = db.usuarios.find((x) => x.id === id)
    if (!u) return error(404, 'Usuario no encontrado')
    const datos = cuerpo(config) as Partial<{ nombre: string; email: string; rol_id: number; activo: boolean;
      cliente_id: string | null }>
    const yo = usuarioDelToken(config, db)
    if (u.id === yo.id && datos.activo === false) {
      return error(400, 'No puedes desactivar tu propia cuenta.')
    }
    if (datos.email && db.usuarios.some((x) => x.email === datos.email && x.id !== id)) {
      return error(400, 'Email ya registrado')
    }
    Object.assign(u, {
      nombre: datos.nombre ?? u.nombre,
      email: datos.email ?? u.email,
      rol_id: datos.rol_id != null ? Number(datos.rol_id) : u.rol_id,
      activo: datos.activo ?? u.activo,
      cliente_id: datos.cliente_id !== undefined ? datos.cliente_id : u.cliente_id,
    })
    guardarDB(db)
    return ok(config, sinPassword(u))
  }

  // ---- deudores ----
  if (metodo === 'GET' && url === '/deudores/buscar') {
    const q = (params.q ?? '').toLowerCase()
    const abiertos = ['activa', 'acuerdo_pago', 'judicial']
    return ok(config, db.deudores
      .filter((d) => d.rut.includes(q.replace(/\./g, '')) || d.nombre.toLowerCase().includes(q))
      .slice(0, 30)
      .map((d) => {
        const suyas = db.cobranzas.filter((c) => c.deudor_id === d.id)
        const abiertas = suyas.filter((c) => abiertos.includes(c.estado))
        return { ...d, total_cobranzas: suyas.length, cobranzas_abiertas: abiertas.length,
          saldo_abierto: abiertas.reduce((s, c) => s + Number(c.monto_actual), 0) }
      }))
  }
  if (metodo === 'GET' && url === '/deudores/') return ok(config, db.deudores)
  if (metodo === 'GET' && /^\/deudores\/[^/]+$/.test(url)) {
    const d = db.deudores.find((x) => x.id === url.split('/')[2])
    return d ? ok(config, d) : error(404, 'Deudor no encontrado')
  }
  if (metodo === 'POST' && /^\/deudores\/[^/]+\/contactos$/.test(url)) {
    const d = db.deudores.find((x) => x.id === url.split('/')[2])
    if (!d) return error(404, 'Deudor no encontrado')
    const datos = cuerpo(config) as { tipo: string; valor: string }
    const nuevo = { id: uid(), deudor_id: d.id, tipo: datos.tipo, valor: datos.valor, activo: true }
    d.contactos.push(nuevo as never)
    guardarDB(db)
    return ok(config, nuevo, 201)
  }
  if (metodo === 'DELETE' && /^\/deudores\/contactos\/[^/]+$/.test(url)) {
    const id = url.split('/')[3]
    for (const d of db.deudores) for (const c of d.contactos) if (c.id === id) c.activo = false
    guardarDB(db)
    return ok(config, null, 204)
  }
  if (metodo === 'POST' && url === '/deudores/') {
    const datos = cuerpo(config) as Record<string, unknown> & { rut: string; contactos?: { tipo: string; valor: string }[] }
    if (db.deudores.some((d) => d.rut === datos.rut)) {
      return error(400, `Ya existe un deudor con RUT ${datos.rut}`)
    }
    const id = uid()
    const nuevo = {
      id, rut: datos.rut, tipo: (datos.tipo as string) ?? 'natural',
      nombre: datos.nombre as string, comuna: (datos.comuna as string) ?? null,
      ciudad: (datos.ciudad as string) ?? null, en_boletin_comercial: false, datos_extra: {},
      observaciones: (datos.observaciones as string) ?? null,
      contactos: (datos.contactos ?? []).map((c) => ({ id: uid(), deudor_id: id, tipo: c.tipo, valor: c.valor, activo: true })),
    }
    db.deudores.push(nuevo as never)
    guardarDB(db)
    return ok(config, nuevo, 201)
  }

  // ---- cobranzas ----
  const conNombres = (c: DB['cobranzas'][number]) => {
    const d = db.deudores.find((x) => x.id === c.deudor_id)
    const cl = db.clientes.find((x) => x.id === c.cliente_id)
    return { ...c, deudor_nombre: d?.nombre ?? null, deudor_rut: d?.rut ?? null,
      cliente_nombre: cl ? (cl.nombre_fantasia ?? cl.razon_social) : null }
  }
  if (metodo === 'GET' && url === '/cobranzas/buscar') {
    const q = (params.q ?? '').toLowerCase()
    const lista = db.cobranzas.filter((c) => {
      const d = db.deudores.find((x) => x.id === c.deudor_id)
      return String(c.numero).includes(q) || (c.id_externo ?? '').toLowerCase().includes(q)
        || d?.rut.includes(q) || d?.nombre.toLowerCase().includes(q)
    })
    return ok(config, lista.slice(0, Number(params.limit) || 50).map(conNombres))
  }
  if (metodo === 'GET' && url === '/cobranzas/') {
    let lista = db.cobranzas
    if (params.estado) lista = lista.filter((c) => c.estado === params.estado)
    if (params.cliente_id) lista = lista.filter((c) => c.cliente_id === params.cliente_id)
    if (params.deudor_id) lista = lista.filter((c) => c.deudor_id === params.deudor_id)
    const skip = Number(params.skip) || 0
    const limit = Number(params.limit) || 100
    const pagina = lista.slice(skip, skip + limit).map(conNombres)
    return ok(config, pagina, 200, { 'x-total-count': String(lista.length) })
  }
  if (metodo === 'GET' && /^\/cobranzas\/[^/]+$/.test(url)) {
    const c = db.cobranzas.find((x) => x.id === url.split('/')[2])
    if (!c) return error(404, 'Cobranza no encontrada')
    return ok(config, {
      ...c,
      cliente: db.clientes.find((x) => x.id === c.cliente_id) ?? null,
      filial: db.filiales.find((x) => x.id === c.filial_id) ?? null,
      deudor: db.deudores.find((x) => x.id === c.deudor_id) ?? null,
    })
  }
  if (metodo === 'POST' && url === '/cobranzas/') {
    const datos = cuerpo(config) as Record<string, string | number | null>
    if (datos.id_externo && db.cobranzas.some((c) => c.cliente_id === datos.cliente_id && c.id_externo === datos.id_externo)) {
      return error(400, 'El ID cliente ya existe para ese cliente')
    }
    const nueva = {
      id: uid(), numero: db.proximoNumero++,
      cliente_id: datos.cliente_id as string, filial_id: (datos.filial_id as number) ?? null,
      deudor_id: datos.deudor_id as string, id_externo: (datos.id_externo as string) ?? null,
      monto_original: String(datos.monto_original), monto_actual: String(datos.monto_original),
      tipo_documento: (datos.tipo_documento as string) ?? 'pagare',
      numero_documento: (datos.numero_documento as string) ?? null,
      fecha_vencimiento_documento: (datos.fecha_vencimiento_documento as string) ?? null,
      datos_extra: (datos.datos_extra as unknown as Record<string, string>) ?? {},
      terceros: [],
      estado: 'activa', tipo: 'extrajudicial',
      fecha_ingreso: hoy(), observaciones: (datos.observaciones as string) ?? null,
    }
    db.cobranzas.push(nueva as never)
    guardarDB(db)
    return ok(config, nueva, 201)
  }

  // ---- gestiones ----
  if (metodo === 'GET' && url === '/gestiones/') {
    const lista = db.gestiones
      .filter((g) => !params.cobranza_id || g.cobranza_id === params.cobranza_id)
      .sort((a, b) => b.fecha_gestion.localeCompare(a.fecha_gestion))
      .map((g) => ({
        ...g,
        es_masivo: (g as { es_masivo?: boolean }).es_masivo ?? false,
        usuario_nombre: db.usuarios.find((u) => u.id === g.usuario_id)?.nombre ?? null,
      }))
    return ok(config, lista)
  }
  if (metodo === 'POST' && url === '/gestiones/') {
    const datos = cuerpo(config) as { cobranza_id: string; tipo_id?: number; descripcion: string }
    const u = usuarioDelToken(config, db)
    const nueva = {
      id: uid(), cobranza_id: datos.cobranza_id, usuario_id: u.id,
      tipo_id: datos.tipo_id ?? null, descripcion: datos.descripcion,
      fecha_gestion: ahora(), fecha_proximo_contacto: null,
    }
    db.gestiones.push(nueva)
    guardarDB(db)
    return ok(config, nueva, 201)
  }

  // ---- acuerdos ----
  if (metodo === 'GET' && url === '/acuerdos/') {
    return ok(config, db.acuerdos.filter((a) => !params.cobranza_id || a.cobranza_id === params.cobranza_id))
  }
  if (metodo === 'GET' && /^\/acuerdos\/[^/]+$/.test(url)) {
    const a = db.acuerdos.find((x) => x.id === url.split('/')[2])
    return a ? ok(config, a) : error(404, 'Acuerdo no encontrado')
  }
  if (metodo === 'POST' && url === '/acuerdos/') {
    const datos = cuerpo(config) as Record<string, string | number>
    const cob = db.cobranzas.find((c) => c.id === datos.cobranza_id)
    if (!cob) return error(404, 'Cobranza no encontrada')
    if (db.acuerdos.some((a) => a.cobranza_id === cob.id && a.estado === 'vigente')) {
      return error(400, 'La cobranza ya tiene un acuerdo vigente.')
    }
    const u = usuarioDelToken(config, db)
    const n = Number(datos.numero_cuotas)
    const total = Number(datos.monto_total_acordado)
    const pie = Number(datos.pie ?? 0)
    const base = Math.round((total - pie) / n)
    const acuerdoId = uid()
    const cuotasNuevas = Array.from({ length: n }, (_, i) => ({
      id: uid(), acuerdo_id: acuerdoId, numero_cuota: i + 1,
      monto: String(i === n - 1 ? total - pie - base * (n - 1) : base),
      fecha_vencimiento: sumarMeses(String(datos.fecha_primera_cuota), i),
      monto_pagado: '0', estado: 'pendiente',
    }))
    const nuevo = {
      id: acuerdoId, cobranza_id: cob.id, estado: 'vigente', fecha_acuerdo: hoy(),
      fecha_termino: cuotasNuevas[n - 1].fecha_vencimiento,
      pie: String(pie), monto_total_acordado: String(total), numero_cuotas: n,
      dia_pago: (datos.dia_pago as number) ?? null,
      fecha_primera_cuota: String(datos.fecha_primera_cuota),
      usuario_id: u.id, cuotas: cuotasNuevas, firma_cliente: 'sin_firmar', observaciones: null,
    }
    db.acuerdos.push(nuevo as never)
    cob.estado = 'acuerdo_pago'
    gestionAutomatica(db, cob.id, u.id, 'acuerdo',
      `ACUERDO DE PAGO: ${clp(total)} en ${n} cuota(s) de ${clp(base)}. ` +
      `Primera cuota vence el ${cuotasNuevas[0].fecha_vencimiento}, última el ${nuevo.fecha_termino}.`)
    guardarDB(db)
    return ok(config, nuevo, 201)
  }

  // ---- pagos (con la cascada del backend real) ----
  if (metodo === 'GET' && url === '/pagos/') {
    return ok(config, db.pagos.filter((p) => !params.cobranza_id || p.cobranza_id === params.cobranza_id))
  }
  if (metodo === 'POST' && url === '/pagos/') {
    const datos = cuerpo(config) as Record<string, string | null>
    const cob = db.cobranzas.find((c) => c.id === datos.cobranza_id)
    if (!cob) return error(404, 'Cobranza no encontrada')
    const u = usuarioDelToken(config, db)
    const monto = Number(datos.monto)
    const capital = Number(datos.capital ?? 0)

    const nuevo = {
      id: uid(), cobranza_id: cob.id, cuota_id: datos.cuota_id ?? null,
      fecha_pago: hoy(), monto: String(monto),
      capital: String(capital),
      honorarios: String(datos.honorarios ?? 0),
      intereses: String(datos.intereses ?? 0),
      gastos_judiciales: String(datos.gastos_judiciales ?? 0),
      forma_pago: (datos.forma_pago as string) ?? null,
      numero_comprobante: (datos.numero_comprobante as string) ?? null,
      estado_pago: (datos.estado_pago as string) ?? 'abono', usuario_id: u.id,
    }
    db.pagos.push(nuevo as never)

    // SOLO el capital descuenta el saldo. Honorarios, interés y gastos varían
    // con la UF del día y NO bajan el saldo capital del cliente (que es lo que
    // muestra la app). Si no se ingresa capital, el saldo no se mueve.
    cob.monto_actual = String(Math.max(0, Number(cob.monto_actual) - capital))

    let numeroCuota: number | null = null
    if (nuevo.cuota_id) {
      const acuerdo = db.acuerdos.find((a) => a.cuotas.some((c) => c.id === nuevo.cuota_id))
      const cuota = acuerdo?.cuotas.find((c) => c.id === nuevo.cuota_id)
      if (acuerdo && cuota) {
        cuota.monto_pagado = String(Number(cuota.monto_pagado) + monto)
        cuota.estado = Number(cuota.monto_pagado) >= Number(cuota.monto) ? 'pagada' : 'pagada_parcial'
        numeroCuota = cuota.numero_cuota
        if (acuerdo.cuotas.every((c) => c.estado === 'pagada')) {
          acuerdo.estado = 'cumplido'
          cob.estado = 'pagada'
        }
      }
    }
    if (Number(cob.monto_actual) === 0) cob.estado = 'pagada'

    // Desglose: solo se listan los conceptos con monto; los vacíos se omiten.
    const desglose: string[] = []
    if (capital > 0) desglose.push(`Saldo Capital: ${clp(capital)}`)
    if (Number(nuevo.honorarios) > 0) desglose.push(`Honorarios: ${clp(Number(nuevo.honorarios))}`)
    if (Number(nuevo.intereses) > 0) desglose.push(`Interés: ${clp(Number(nuevo.intereses))}`)
    if (Number(nuevo.gastos_judiciales) > 0) desglose.push(`Gastos judiciales: ${clp(Number(nuevo.gastos_judiciales))}`)
    const encabezado = numeroCuota
      ? `Pago de cuota ${numeroCuota} por un total de ${clp(monto)}`
      : `Se realizó un abono por un total de ${clp(monto)}`
    const detalle = desglose.length ? ` Desglose: ${desglose.join(' · ')}.` : ''
    gestionAutomatica(db, cob.id, u.id, 'abono',
      `${encabezado}.${detalle} Saldo capital restante: ${clp(Number(cob.monto_actual))}.`)
    if (cob.estado === 'pagada') {
      gestionAutomatica(db, cob.id, u.id, 'pagado', 'CUENTA SALDADA. La cobranza queda en estado pagada.')
    }
    guardarDB(db)
    return ok(config, nuevo, 201)
  }

  // ---- panel de indicadores ----
  if (metodo === 'GET' && url === '/panel') {
    const hoyIso = hoy()
    const desde = params.desde ?? hoyIso.slice(0, 8) + '01'
    const hasta = params.hasta ?? hoyIso
    const delCliente = (cobranzaId: string) => {
      const c = db.cobranzas.find((x) => x.id === cobranzaId)
      return !params.cliente_id || c?.cliente_id === params.cliente_id
    }
    const sumar = (lista: typeof db.pagos) => ({
      total: String(lista.reduce((s, x) => s + Number(x.monto), 0)),
      capital: String(lista.reduce((s, x) => s + Number(x.capital), 0)),
      honorarios: String(lista.reduce((s, x) => s + Number(x.honorarios), 0)),
      intereses: String(lista.reduce((s, x) => s + Number(x.intereses), 0)),
      pagos: lista.length,
    })
    const pagos = db.pagos.filter((x) => delCliente(x.cobranza_id))
    const dias = (Date.parse(hasta) - Date.parse(desde)) / 86400000 + 1
    const desdeAnt = new Date(Date.parse(desde) - dias * 86400000).toISOString().slice(0, 10)
    const cobs = db.cobranzas.filter((c) => !params.cliente_id || c.cliente_id === params.cliente_id)
    const estados = new Map<string, { cantidad: number; saldo: number; original: number }>()
    for (const c of cobs) {
      const e = estados.get(c.estado) ?? { cantidad: 0, saldo: 0, original: 0 }
      e.cantidad++; e.saldo += Number(c.monto_actual); e.original += Number(c.monto_original)
      estados.set(c.estado, e)
    }
    const cuotasAbiertas = db.acuerdos.filter((a) => a.estado === 'vigente' && delCliente(a.cobranza_id))
      .flatMap((a) => a.cuotas).filter((cu) => cu.estado !== 'pagada' && cu.fecha_vencimiento < hoyIso)
    const vencidasPeriodo = db.acuerdos.filter((a) => delCliente(a.cobranza_id)).flatMap((a) => a.cuotas)
      .filter((cu) => cu.fecha_vencimiento >= desde && cu.fecha_vencimiento <= (hasta < hoyIso ? hasta : hoyIso))
    const meses = Array.from({ length: 12 }, (_, i) => {
      const d = new Date(); d.setDate(1); d.setMonth(d.getMonth() - (11 - i))
      const mes = d.toISOString().slice(0, 7)
      const delMes = pagos.filter((x) => x.fecha_pago.startsWith(mes))
      const s = sumar(delMes)
      return { mes: mes + '-01', capital: s.capital, honorarios: s.honorarios,
        otros: String(Number(s.total) - Number(s.capital) - Number(s.honorarios)), total: s.total }
    })
    const porCliente = db.clientes.map((cl) => {
      const suyas = db.cobranzas.filter((c) => c.cliente_id === cl.id)
      const abiertas = suyas.filter((c) => ['activa', 'acuerdo_pago', 'judicial'].includes(c.estado))
      const pagosCl = db.pagos.filter((x) => suyas.some((c) => c.id === x.cobranza_id))
      return { cliente_id: cl.id, cliente: cl.nombre_fantasia ?? cl.razon_social, abiertas: abiertas.length,
        saldo: String(abiertas.reduce((s, c) => s + Number(c.monto_actual), 0)),
        asignado: String(suyas.reduce((s, c) => s + Number(c.monto_original), 0)),
        recuperado_periodo: String(pagosCl.filter((x) => x.fecha_pago >= desde && x.fecha_pago <= hasta)
          .reduce((s, x) => s + Number(x.capital), 0)),
        recuperado_total: String(pagosCl.reduce((s, x) => s + Number(x.capital), 0)) }
    }).filter((c) => !params.cliente_id || c.cliente_id === params.cliente_id)
    return ok(config, {
      desde, hasta,
      recupero: sumar(pagos.filter((x) => x.fecha_pago >= desde && x.fecha_pago <= hasta)),
      recupero_anterior: sumar(pagos.filter((x) => x.fecha_pago >= desdeAnt && x.fecha_pago < desde)),
      cartera: [...estados.entries()].map(([estado, e]) => ({ estado, cantidad: e.cantidad,
        saldo: String(e.saldo), original: String(e.original) })).sort((a, b) => b.cantidad - a.cantidad),
      cuotas_atrasadas: cuotasAbiertas.length,
      monto_atrasado: String(cuotasAbiertas.reduce((s, cu) => s + Number(cu.monto) - Number(cu.monto_pagado), 0)),
      cuotas_vencidas_periodo: vencidasPeriodo.length,
      cuotas_pagadas_periodo: vencidasPeriodo.filter((cu) => cu.estado === 'pagada').length,
      gestiones_periodo: db.gestiones.filter((g) => g.fecha_gestion.slice(0, 10) >= desde && delCliente(g.cobranza_id)).length,
      sin_gestion_30_dias: cobs.filter((c) => ['activa', 'acuerdo_pago', 'judicial'].includes(c.estado)
        && !db.gestiones.some((g) => g.cobranza_id === c.id
          && Date.parse(g.fecha_gestion) > Date.now() - 30 * 86400000)).length,
      meses, por_cliente: porCliente,
    })
  }

  // ---- reportes (admin) ----
  if (metodo === 'GET' && url === '/reportes/equipo') {
    const reporte = db.usuarios.map((u) => {
      const gestionesU = db.gestiones.filter((g) => g.usuario_id === u.id)
      const porTipo: Record<string, number> = {}
      for (const g of gestionesU) {
        const nombre = db.tiposGestion.find((t) => t.id === g.tipo_id)?.nombre ?? 'Sin tipo'
        porTipo[nombre] = (porTipo[nombre] ?? 0) + 1
      }
      const pagosU = db.pagos.filter((p) => p.usuario_id === u.id)
      return {
        usuario_id: u.id, nombre: u.nombre, activo: u.activo,
        gestiones_total: gestionesU.length, gestiones_por_tipo: porTipo,
        acuerdos_creados: db.acuerdos.filter((a) => a.usuario_id === u.id).length,
        pagos_ingresados: pagosU.length,
        monto_pagos: String(pagosU.reduce((s, p) => s + Number(p.monto), 0)),
      }
    })
    return ok(config, reporte)
  }

  // ---- portal de mandantes ----
  if (url.startsWith('/portal/')) {
    const u = usuarioDelToken(config, db)
    if (u.rol_id !== 7 || !u.cliente_id) return error(403, 'Esta sección es para los usuarios del portal de clientes.')
    const propias = db.cobranzas.filter((c) => c.cliente_id === u.cliente_id)
    const ids = new Set(propias.map((c) => c.id))
    const abiertos = ['activa', 'acuerdo_pago', 'judicial']
    const internos = new Set(db.tiposGestion.filter((t) => t.codigo === 'nota' || t.codigo === 'automatica').map((t) => t.id))
    const visibles = (cobranzaId: string) => db.gestiones
      .filter((g) => g.cobranza_id === cobranzaId && !(g.tipo_id !== null && internos.has(g.tipo_id)))
      .sort((a, b) => b.fecha_gestion.localeCompare(a.fecha_gestion))
    const vista = (c: DB['cobranzas'][number]) => {
      const d = db.deudores.find((x) => x.id === c.deudor_id)
      return { id: c.id, numero: c.numero, id_externo: c.id_externo, deudor: d?.nombre ?? '', rut: d?.rut ?? '',
        monto_original: c.monto_original, monto_actual: c.monto_actual, estado: c.estado,
        fecha_ingreso: c.fecha_ingreso, ultima_gestion: visibles(c.id)[0]?.fecha_gestion.slice(0, 10) ?? null }
    }
    const pendientes = db.acuerdos.filter((a) => ids.has(a.cobranza_id) && a.estado === 'vigente'
      && a.firma_cliente !== 'firmado_confirmado')

    if (metodo === 'GET' && url === '/portal/resumen') {
      const pagos = db.pagos.filter((x) => ids.has(x.cobranza_id))
      const capital = (lista: typeof pagos) => String(lista.reduce((s, x) => s + Number(x.capital), 0))
      const abiertas = propias.filter((c) => abiertos.includes(c.estado))
      const cli = db.clientes.find((c) => c.id === u.cliente_id)
      const meses = Array.from({ length: 12 }, (_, i) => {
        const d = new Date(); d.setDate(1); d.setMonth(d.getMonth() - (11 - i))
        const mes = d.toISOString().slice(0, 7)
        return { mes: mes + '-01', capital: capital(pagos.filter((x) => x.fecha_pago.startsWith(mes))) }
      })
      return ok(config, {
        cliente: cli ? cli.nombre_fantasia ?? cli.razon_social : '', estudio: db.empresa.nombre_fantasia,
        asignado: String(propias.reduce((s, c) => s + Number(c.monto_original), 0)),
        saldo_abierto: String(abiertas.reduce((s, c) => s + Number(c.monto_actual), 0)),
        casos_abiertos: abiertas.length, casos_totales: propias.length,
        recuperado_total: capital(pagos), recuperado_mes: capital(pagos.filter((x) => x.fecha_pago.startsWith(hoy().slice(0, 7)))),
        acuerdos_vigentes: db.acuerdos.filter((a) => ids.has(a.cobranza_id) && a.estado === 'vigente').length,
        acuerdos_por_aprobar: pendientes.length, meses,
      })
    }
    if (metodo === 'GET' && url === '/portal/cobranzas') {
      const q = (params.q ?? '').trim().toLowerCase()
      const lista = propias
        .filter((c) => !params.estado || c.estado === params.estado)
        .map(vista)
        .filter((c) => !q || c.deudor.toLowerCase().includes(q) || c.rut.includes(q.replace(/\./g, ''))
          || (c.id_externo ?? '').toLowerCase().includes(q))
        .sort((a, b) => b.numero - a.numero)
      const skip = Number(params.skip) || 0
      const limit = Number(params.limit) || 50
      return ok(config, lista.slice(skip, skip + limit), 200, { 'x-total-count': String(lista.length) })
    }
    if (metodo === 'GET' && /^\/portal\/cobranzas\/[^/]+$/.test(url)) {
      const c = propias.find((x) => x.id === url.split('/')[3])
      if (!c) return error(404, 'Cobranza no encontrada')
      const tipo = (id: number | null) => db.tiposGestion.find((t) => t.id === id)?.nombre ?? null
      const acuerdo = db.acuerdos.filter((a) => a.cobranza_id === c.id).pop() ?? null
      return ok(config, {
        ...vista(c),
        gestiones: visibles(c.id).map((g) => ({ fecha: g.fecha_gestion.slice(0, 10), tipo: tipo(g.tipo_id), descripcion: g.descripcion })),
        pagos: db.pagos.filter((x) => x.cobranza_id === c.id)
          .map((x) => ({ fecha_pago: x.fecha_pago, monto: x.monto, capital: x.capital, forma_pago: x.forma_pago })),
        acuerdo,
      })
    }
    if (metodo === 'GET' && url === '/portal/acuerdos/pendientes') {
      return ok(config, pendientes.map((a) => {
        const c = propias.find((x) => x.id === a.cobranza_id)!
        return { id: a.id, cobranza_id: c.id, numero_cobranza: c.numero, deudor: vista(c).deudor,
          fecha_acuerdo: a.fecha_acuerdo, pie: a.pie, monto_total_acordado: a.monto_total_acordado,
          numero_cuotas: a.numero_cuotas, firma_cliente: a.firma_cliente, observaciones: a.observaciones }
      }))
    }
    const accion = /^\/portal\/acuerdos\/([^/]+)\/(aprobar|observar)$/.exec(url)
    if (metodo === 'POST' && accion) {
      const a = db.acuerdos.find((x) => x.id === accion[1] && ids.has(x.cobranza_id))
      if (!a) return error(404, 'Acuerdo no encontrado')
      if (accion[2] === 'aprobar') {
        a.firma_cliente = 'firmado_confirmado'
        gestionAutomatica(db, a.cobranza_id, u.id, 'acuerdo', `Acuerdo APROBADO por el mandante (${u.nombre}) desde el portal.`)
      } else {
        const { motivo } = cuerpo(config) as { motivo: string }
        if (!motivo || motivo.trim().length < 3) return error(422, 'Indica el motivo.')
        a.firma_cliente = 'pendiente'
        gestionAutomatica(db, a.cobranza_id, u.id, 'acuerdo', `El mandante (${u.nombre}) NO aprueba el acuerdo: ${motivo.trim()}`)
      }
      guardarDB(db)
      return ok(config, null, 204)
    }
  }

  // ---- lo que necesita servidor de verdad ----
  return error(501, 'Esta función (descargas Excel/Word, carga masiva) está disponible en la versión completa con servidor.')
}

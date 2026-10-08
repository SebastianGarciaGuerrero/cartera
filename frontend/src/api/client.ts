import axios from 'axios'
import type { AxiosError, InternalAxiosRequestConfig } from 'axios'

// Cliente HTTP central.
//
// Seguridad de la sesión:
//  - El access token (15 min) vive SOLO en memoria de esta pestaña: no va a
//    localStorage, así un script inyectado no puede robarlo para usarlo
//    después.
//  - La sesión larga es una cookie httpOnly que JavaScript no puede leer;
//    con ella se pide un access token nuevo (/auth/refresh) al cargar la
//    página y cuando el actual vence. Si dos peticiones fallan a la vez,
//    se hace un solo refresh y ambas se reintentan.

// MODO DEMO (npm run build:demo): sin servidor, los datos viven en el
// navegador. Sirve para publicar solo el frontend (ej. Vercel).
export const ES_DEMO = import.meta.env.MODE === 'demo'

let accessToken: string | null = null

export function fijarToken(token: string | null) {
  accessToken = token
}

export const api = axios.create({
  baseURL: '/api',
  withCredentials: true,
  // Cabecera que un formulario de otro sitio no puede mandar: el backend la
  // exige en los endpoints que usan la cookie de sesión.
  headers: { 'X-Requested-With': 'cartera' },
})

// En modo demo, el transporte HTTP se reemplaza por el backend simulado del
// navegador. Se exporta la promesa para que main.tsx espere a que el
// adaptador esté instalado ANTES de montar la app.
export const adaptadorListo: Promise<void> = ES_DEMO
  ? import('./demo').then(({ adaptadorDemo }) => {
      api.defaults.adapter = adaptadorDemo
    })
  : Promise.resolve()

api.interceptors.request.use((config) => {
  if (accessToken) config.headers.Authorization = `Bearer ${accessToken}`
  return config
})

// Respuesta del login / refresh.
export interface RespuestaToken {
  access_token: string
  expira_en: number
  usuario: import('./tipos').UsuarioActual
}

let refrescoEnCurso: Promise<RespuestaToken | null> | null = null
let alPerderSesion: () => void = () => {}

export function registrarSesionPerdida(fn: () => void) {
  alPerderSesion = fn
}

/** Pide un access token nuevo con la cookie. null si no hay sesión. */
export function refrescarSesion(): Promise<RespuestaToken | null> {
  if (!refrescoEnCurso) {
    refrescoEnCurso = api
      .post<RespuestaToken>('/auth/refresh')
      .then((r) => {
        fijarToken(r.data.access_token)
        return r.data
      })
      .catch(() => {
        fijarToken(null)
        return null
      })
      .finally(() => {
        refrescoEnCurso = null
      })
  }
  return refrescoEnCurso
}

type ConfigReintento = InternalAxiosRequestConfig & { _sinReintento?: boolean; _reintentado?: boolean }

api.interceptors.response.use(
  (res) => res,
  async (error: AxiosError) => {
    const config = error.config as ConfigReintento | undefined
    const esAuth = config?.url?.startsWith('/auth/login') || config?.url?.startsWith('/auth/refresh')
    if (error.response?.status === 401 && config && !config._sinReintento && !config._reintentado && !esAuth) {
      config._reintentado = true
      const nueva = await refrescarSesion()
      if (nueva) return api(config)
      alPerderSesion()
    }
    return Promise.reject(error)
  },
)

/** Descarga un archivo del backend (Excel/Word) respetando el token. */
export async function descargarArchivo(ruta: string, params?: Record<string, string>) {
  if (ES_DEMO) {
    alert('Las descargas (Excel y Word) funcionan en la versión completa, que corre con servidor y base de datos. Esta demo muestra la interfaz y el flujo de trabajo.')
    return
  }
  const res = await api.get(ruta, { params, responseType: 'blob' })
  const disposicion: string = res.headers['content-disposition'] ?? ''
  const nombre = /filename="?([^";]+)"?/.exec(disposicion)?.[1] ?? 'archivo'
  const url = URL.createObjectURL(res.data)
  const a = document.createElement('a')
  a.href = url
  a.download = nombre
  a.click()
  URL.revokeObjectURL(url)
}

/** Extrae un mensaje legible del error de la API (detail de FastAPI). */
export function mensajeDeError(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detalle = error.response?.data?.detail
    if (typeof detalle === 'string') return detalle
    if (Array.isArray(detalle)) return detalle.map((d) => String(d.msg).replace(/^Value error, /, '')).join('; ')
    if (error.response?.status === 429) return 'Demasiados intentos. Espera unos minutos.'
  }
  return 'Error inesperado. Revisa la conexión con el servidor.'
}

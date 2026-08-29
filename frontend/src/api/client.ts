import axios from 'axios'

// Cliente HTTP central. El token JWT viaja en cada petición; si el backend
// responde 401 (token vencido o inválido), se limpia la sesión y se vuelve
// al login.

export const TOKEN_KEY = 'cartera_token'

// MODO DEMO (npm run build:demo): sin servidor, los datos viven en el
// navegador. Sirve para publicar solo el frontend (ej. Vercel).
export const ES_DEMO = import.meta.env.MODE === 'demo'

export const api = axios.create({ baseURL: '/api' })

// En modo demo, el transporte HTTP se reemplaza por el backend simulado del
// navegador. Se exporta la promesa para que main.tsx espere a que el
// adaptador esté instalado ANTES de montar la app; si no, la primera
// petición (validar sesión) saldría a la red real y cerraría la sesión.
export const adaptadorListo: Promise<void> = ES_DEMO
  ? import('./demo').then(({ adaptadorDemo }) => {
      api.defaults.adapter = adaptadorDemo
    })
  : Promise.resolve()

api.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (res) => res,
  (error) => {
    if (error.response?.status === 401 && window.location.pathname !== '/login') {
      localStorage.removeItem(TOKEN_KEY)
      window.location.href = '/login'
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
    if (Array.isArray(detalle)) return detalle.map((d) => d.msg).join('; ')
  }
  return 'Error inesperado. Revisa la conexión con el servidor.'
}

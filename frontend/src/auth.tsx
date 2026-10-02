import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { api, fijarToken, refrescarSesion, registrarSesionPerdida } from './api/client'
import type { RespuestaToken } from './api/client'
import type { UsuarioActual } from './api/tipos'

// Sesión de la app. Al cargar la página se pide un access token con la
// cookie de sesión (si existe); el token queda solo en memoria.

export type ResultadoLogin = { ok: true } | { ok: false; mfaToken: string }

interface Sesion {
  usuario: UsuarioActual | null
  cargando: boolean
  login: (email: string, password: string) => Promise<ResultadoLogin>
  completarMfa: (mfaToken: string, codigo: string) => Promise<void>
  logout: () => Promise<void>
  recargar: () => Promise<void>
  esAdmin: boolean
  /** ¿El plan de la organización incluye esta función? */
  tiene: (funcion: string) => boolean
  /** Cómo llama esta organización a las cosas (Cliente/Mandante...). */
  etiqueta: (clave: string, porDefecto: string) => string
}

const ContextoAuth = createContext<Sesion>(null!)

export function useAuth() {
  return useContext(ContextoAuth)
}

export function ProveedorAuth({ children }: { children: ReactNode }) {
  const [usuario, setUsuario] = useState<UsuarioActual | null>(null)
  const [cargando, setCargando] = useState(true)

  const aplicar = useCallback((r: RespuestaToken) => {
    fijarToken(r.access_token)
    setUsuario(r.usuario)
  }, [])

  useEffect(() => {
    registrarSesionPerdida(() => {
      fijarToken(null)
      setUsuario(null)
    })
    refrescarSesion()
      .then((r) => { if (r) setUsuario(r.usuario) })
      .finally(() => setCargando(false))
  }, [])

  async function login(email: string, password: string): Promise<ResultadoLogin> {
    const { data } = await api.post('/auth/login', { email, password })
    if (data.requiere_mfa) return { ok: false, mfaToken: data.mfa_token }
    aplicar(data as RespuestaToken)
    return { ok: true }
  }

  async function completarMfa(mfaToken: string, codigo: string) {
    const { data } = await api.post<RespuestaToken>('/auth/login/mfa', { mfa_token: mfaToken, codigo })
    aplicar(data)
  }

  async function logout() {
    try {
      await api.post('/auth/logout')
    } finally {
      fijarToken(null)
      setUsuario(null)
    }
  }

  async function recargar() {
    const { data } = await api.get<UsuarioActual>('/auth/me')
    setUsuario(data)
  }

  const funciones = new Set(usuario?.organizacion.funciones ?? [])
  const etiquetas = usuario?.organizacion.etiquetas ?? {}

  return (
    <ContextoAuth.Provider value={{
      usuario, cargando, login, completarMfa, logout, recargar,
      esAdmin: usuario?.rol === 'admin',
      tiene: (f) => funciones.has(f),
      etiqueta: (clave, porDefecto) => etiquetas[clave] || porDefecto,
    }}>
      {children}
    </ContextoAuth.Provider>
  )
}

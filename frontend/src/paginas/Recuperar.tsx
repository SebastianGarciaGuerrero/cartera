import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, mensajeDeError } from '../api/client'
import { MARCA } from '../marca'

// Dos pantallas públicas:
//  /recuperar    → pide el email y manda un enlace (la respuesta es la misma
//                  exista o no la cuenta, para no revelar quién está registrado).
//  /restablecer  → llega desde el enlace del correo (recuperación o
//                  invitación de bienvenida) y fija la contraseña nueva.

function Marco({ children, onSubmit }: { children: React.ReactNode; onSubmit: (e: FormEvent) => void }) {
  return (
    <div className="login-fondo">
      <form className="login-caja" onSubmit={onSubmit}>
        <div className="login-marca">
          <img className="login-logo" src="/logo.svg" alt={MARCA.nombre} />
          <div className="login-titulo">{MARCA.nombre.toUpperCase()}</div>
        </div>
        {children}
      </form>
    </div>
  )
}

export function Recuperar() {
  const [email, setEmail] = useState('')
  const [enviado, setEnviado] = useState(false)
  const [error, setError] = useState('')
  const [enviando, setEnviando] = useState(false)

  async function alEnviar(e: FormEvent) {
    e.preventDefault()
    setError('')
    setEnviando(true)
    try {
      await api.post('/auth/recuperar', { email })
      setEnviado(true)
    } catch (err) {
      setError(mensajeDeError(err))
    } finally {
      setEnviando(false)
    }
  }

  return (
    <Marco onSubmit={alEnviar}>
      {enviado ? (
        <div className="alerta-exito">
          Si <strong>{email}</strong> tiene una cuenta, te enviamos un enlace para elegir
          una contraseña nueva. Vale por 30 minutos. Revisa también la carpeta de spam.
        </div>
      ) : (
        <>
          <p className="nota">Escribe tu email y te enviaremos un enlace para elegir una contraseña nueva.</p>
          <label>
            Email
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoFocus required />
          </label>
          {error && <div className="alerta-error">{error}</div>}
          <button className="btn btn-primario" disabled={enviando}>
            {enviando ? 'Enviando…' : 'Enviar enlace'}
          </button>
        </>
      )}
      <Link to="/login" className="suave">Volver al ingreso</Link>
    </Marco>
  )
}

export function Restablecer() {
  const [params] = useSearchParams()
  const navegar = useNavigate()
  const token = params.get('token') ?? ''
  const bienvenida = params.get('bienvenida') === '1'
  const [password, setPassword] = useState('')
  const [repetir, setRepetir] = useState('')
  const [error, setError] = useState('')
  const [listo, setListo] = useState(false)
  const [enviando, setEnviando] = useState(false)

  async function alEnviar(e: FormEvent) {
    e.preventDefault()
    setError('')
    if (password !== repetir) {
      setError('Las contraseñas no coinciden.')
      return
    }
    setEnviando(true)
    try {
      await api.post('/auth/restablecer', { token, password_nueva: password })
      setListo(true)
      setTimeout(() => navegar('/login'), 2500)
    } catch (err) {
      setError(mensajeDeError(err))
    } finally {
      setEnviando(false)
    }
  }

  return (
    <Marco onSubmit={alEnviar}>
      {listo ? (
        <div className="alerta-exito">Contraseña guardada. Te llevamos al ingreso…</div>
      ) : (
        <>
          <p className="nota">
            {bienvenida ? '¡Bienvenido! Elige tu contraseña para entrar.' : 'Elige tu contraseña nueva.'}
            {' '}Mínimo 12 caracteres; una frase fácil de recordar funciona bien
            (ej. <span className="mono">cobranza-de-los-martes</span>).
          </p>
          <label>
            Contraseña nueva
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password" minLength={12} autoFocus required />
          </label>
          <label>
            Repetir contraseña
            <input type="password" value={repetir} onChange={(e) => setRepetir(e.target.value)}
              autoComplete="new-password" minLength={12} required />
          </label>
          {!token && <div className="alerta-error">El enlace está incompleto. Pide uno nuevo.</div>}
          {error && <div className="alerta-error">{error}</div>}
          <button className="btn btn-primario" disabled={enviando || !token}>
            {enviando ? 'Guardando…' : 'Guardar contraseña'}
          </button>
        </>
      )}
      <Link to="/login" className="suave">Volver al ingreso</Link>
    </Marco>
  )
}

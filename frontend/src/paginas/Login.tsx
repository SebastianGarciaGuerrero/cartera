import { useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import { mensajeDeError, ES_DEMO } from '../api/client'
import { MARCA } from '../marca'

export default function Login() {
  const { login } = useAuth()
  const navegar = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [enviando, setEnviando] = useState(false)

  async function alEnviar(e: FormEvent) {
    e.preventDefault()
    setError('')
    setEnviando(true)
    try {
      await login(email, password)
      navegar('/cobranzas')
    } catch (err) {
      setError(mensajeDeError(err))
    } finally {
      setEnviando(false)
    }
  }

  return (
    <div className="login-fondo">
      <form className="login-caja" onSubmit={alEnviar}>
        <div className="login-marca">
          <img className="login-logo" src="/logo.svg" alt={MARCA.nombre} />
          <div className="login-titulo">{MARCA.nombre.toUpperCase()}</div>
          <div className="login-subtitulo">{MARCA.eslogan}</div>
        </div>

        <label>
          Email
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="tu@empresa.cl"
            autoFocus
            required
          />
        </label>

        <label>
          Contraseña
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>

        {error && <div className="alerta-error">{error}</div>}

        {ES_DEMO && (
          <div className="aviso-demo">
            <strong>Versión demo</strong> — los datos son de práctica y se
            guardan solo en este navegador.<br />
            Entra con <span className="mono">admin@demo.cl</span> /{' '}
            <span className="mono">demo1234</span>
          </div>
        )}

        <button className="btn btn-primario" disabled={enviando}>
          {enviando ? 'Ingresando…' : 'Ingresar'}
        </button>

        <div className="pie-firma">
          Creado por{' '}
          <a href="https://sebastiangarcia.cl" target="_blank" rel="noreferrer">
            sebastiangarcia.cl
          </a>
        </div>
      </form>
    </div>
  )
}

import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import { mensajeDeError, ES_DEMO } from '../api/client'
import { MARCA } from '../marca'

// Ingreso en dos pasos cuando la cuenta tiene 2FA: primero email y
// contraseña; si corresponde, después el código de 6 dígitos de la app
// autenticadora (o un código de recuperación).

export default function Login() {
  const { login, completarMfa } = useAuth()
  const navegar = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [mfaToken, setMfaToken] = useState<string | null>(null)
  const [codigo, setCodigo] = useState('')
  const [usarRecuperacion, setUsarRecuperacion] = useState(false)
  const [error, setError] = useState('')
  const [enviando, setEnviando] = useState(false)

  async function alEnviar(e: FormEvent) {
    e.preventDefault()
    setError('')
    setEnviando(true)
    try {
      if (mfaToken) {
        await completarMfa(mfaToken, codigo.trim())
        navegar('/')
      } else {
        const r = await login(email, password)
        if (r.ok) navegar('/')
        else setMfaToken(r.mfaToken)
      }
    } catch (err) {
      setError(mensajeDeError(err))
      if (mfaToken) setCodigo('')
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

        {!mfaToken ? (
          <>
            <label>
              Email
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="tu@empresa.cl"
                autoComplete="username"
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
                autoComplete="current-password"
                required
              />
            </label>
          </>
        ) : (
          <label>
            {usarRecuperacion ? 'Código de recuperación' : 'Código de verificación'}
            <input
              value={codigo}
              onChange={(e) => setCodigo(e.target.value)}
              placeholder={usarRecuperacion ? 'xxxxx-xxxxx' : '6 dígitos de tu app autenticadora'}
              inputMode={usarRecuperacion ? 'text' : 'numeric'}
              autoComplete="one-time-code"
              maxLength={usarRecuperacion ? 11 : 6}
              autoFocus
              required
            />
            <button
              type="button"
              className="btn btn-chico btn-secundario"
              onClick={() => { setUsarRecuperacion(!usarRecuperacion); setCodigo('') }}
            >
              {usarRecuperacion ? 'Usar el código de la app' : 'Perdí el teléfono: usar código de recuperación'}
            </button>
          </label>
        )}

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
          {enviando ? 'Verificando…' : mfaToken ? 'Verificar' : 'Ingresar'}
        </button>

        {mfaToken ? (
          <button type="button" className="btn btn-secundario"
            onClick={() => { setMfaToken(null); setCodigo(''); setError('') }}>
            Volver
          </button>
        ) : (
          !ES_DEMO && <Link to="/recuperar" className="suave">¿Olvidaste tu contraseña?</Link>
        )}

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

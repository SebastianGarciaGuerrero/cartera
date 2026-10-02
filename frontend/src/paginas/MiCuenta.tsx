import { useState } from 'react'
import type { FormEvent } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, mensajeDeError, ES_DEMO } from '../api/client'
import { useAuth } from '../auth'
import type { SesionActiva } from '../api/tipos'
import { fechaHoraLegible } from '../componentes/utiles'

// Mi cuenta: cambiar contraseña, activar la verificación en dos pasos (2FA)
// y ver/cerrar las sesiones abiertas en otros equipos.

export default function MiCuenta() {
  const { usuario } = useAuth()
  if (!usuario) return null
  return (
    <>
      <header className="pagina-cabecera">
        <h1>Mi cuenta</h1>
      </header>
      {usuario.debe_cambiar_password && (
        <div className="alerta-error">
          Tu contraseña es temporal: cámbiala antes de seguir trabajando.
        </div>
      )}
      <CambiarPassword />
      {!ES_DEMO && <SegundoFactor />}
      {!ES_DEMO && <Sesiones />}
    </>
  )
}

function CambiarPassword() {
  const { recargar } = useAuth()
  const [actual, setActual] = useState('')
  const [nueva, setNueva] = useState('')
  const [repetir, setRepetir] = useState('')
  const [error, setError] = useState('')
  const [ok, setOk] = useState(false)

  const guardar = useMutation({
    mutationFn: () => api.put('/auth/cambiar-password', { password_actual: actual, password_nueva: nueva }),
    onSuccess: async () => {
      setOk(true); setError(''); setActual(''); setNueva(''); setRepetir('')
      await recargar()
    },
    onError: (err) => { setOk(false); setError(mensajeDeError(err)) },
  })

  function alEnviar(e: FormEvent) {
    e.preventDefault()
    if (nueva !== repetir) { setError('Las contraseñas nuevas no coinciden.'); return }
    guardar.mutate()
  }

  return (
    <form className="form-finanzas form-alta" onSubmit={alEnviar}>
      <h3>Contraseña</h3>
      <div className="fila">
        <label>
          Contraseña actual
          <input type="password" value={actual} onChange={(e) => setActual(e.target.value)}
            autoComplete="current-password" required />
        </label>
        <label>
          Nueva (mín. 12 caracteres)
          <input type="password" value={nueva} onChange={(e) => setNueva(e.target.value)}
            autoComplete="new-password" minLength={12} required />
        </label>
        <label>
          Repetir nueva
          <input type="password" value={repetir} onChange={(e) => setRepetir(e.target.value)}
            autoComplete="new-password" minLength={12} required />
        </label>
      </div>
      <p className="nota">Al cambiarla se cierran tus sesiones abiertas en otros equipos.</p>
      {error && <div className="alerta-error">{error}</div>}
      {ok && <div className="alerta-exito">Contraseña actualizada.</div>}
      <div className="fila">
        <button className="btn btn-primario" disabled={guardar.isPending}>
          {guardar.isPending ? 'Guardando…' : 'Cambiar contraseña'}
        </button>
      </div>
    </form>
  )
}

function SegundoFactor() {
  const { usuario, recargar } = useAuth()
  const [qr, setQr] = useState<{ qr: string; secreto: string } | null>(null)
  const [codigo, setCodigo] = useState('')
  const [codigos, setCodigos] = useState<string[] | null>(null)
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')

  const iniciar = useMutation({
    mutationFn: async () => (await api.post('/auth/mfa/iniciar')).data,
    onSuccess: (d) => { setQr(d); setError('') },
    onError: (err) => setError(mensajeDeError(err)),
  })
  const confirmar = useMutation({
    mutationFn: async () => (await api.post('/auth/mfa/confirmar', { codigo })).data,
    onSuccess: async (d) => { setCodigos(d.codigos); setQr(null); setCodigo(''); setError(''); await recargar() },
    onError: (err) => setError(mensajeDeError(err)),
  })
  const desactivar = useMutation({
    mutationFn: () => api.post('/auth/mfa/desactivar', { password, codigo }),
    onSuccess: async () => { setPassword(''); setCodigo(''); setError(''); await recargar() },
    onError: (err) => setError(mensajeDeError(err)),
  })

  return (
    <section className="form-finanzas form-alta">
      <h3>Verificación en dos pasos (2FA)</h3>
      {codigos ? (
        <>
          <div className="alerta-exito">2FA activado.</div>
          <p className="nota">
            Guarda estos códigos de recuperación en un lugar seguro (se muestran UNA sola vez).
            Cada uno sirve una vez para entrar si pierdes el teléfono.
          </p>
          <pre className="mono">{codigos.join('\n')}</pre>
          <div className="fila">
            <button className="btn btn-secundario" type="button"
              onClick={() => navigator.clipboard.writeText(codigos.join('\n'))}>Copiar</button>
            <button className="btn btn-primario" type="button" onClick={() => setCodigos(null)}>Ya los guardé</button>
          </div>
        </>
      ) : usuario?.mfa_activo ? (
        <>
          <p>Está <strong>activado</strong>: al entrar se te pide el código de tu app autenticadora.</p>
          <div className="fila">
            <label>Contraseña
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
            </label>
            <label>Código actual
              <input value={codigo} onChange={(e) => setCodigo(e.target.value)} inputMode="numeric" />
            </label>
          </div>
          <div className="fila">
            <button className="btn btn-secundario" type="button" disabled={desactivar.isPending}
              onClick={() => desactivar.mutate()}>Desactivar 2FA</button>
          </div>
        </>
      ) : qr ? (
        <>
          <p className="nota">
            1. Escanea el código con Google Authenticator, Microsoft Authenticator u otra app similar.<br />
            2. Escribe el código de 6 dígitos que aparece.
          </p>
          <img src={qr.qr} alt="Código QR para la app autenticadora" width={200} height={200} />
          <p className="nota">¿No puedes escanear? Ingresa esta clave a mano: <span className="mono">{qr.secreto}</span></p>
          <div className="fila">
            <label>Código de 6 dígitos
              <input value={codigo} onChange={(e) => setCodigo(e.target.value)} inputMode="numeric"
                maxLength={6} autoFocus />
            </label>
          </div>
          <div className="fila">
            <button className="btn btn-primario" type="button" disabled={codigo.length !== 6 || confirmar.isPending}
              onClick={() => confirmar.mutate()}>Activar</button>
            <button className="btn btn-secundario" type="button" onClick={() => setQr(null)}>Cancelar</button>
          </div>
        </>
      ) : (
        <>
          <p>
            Agrega una segunda llave a tu cuenta: además de la contraseña, un código que cambia cada
            30 segundos en tu teléfono. Muy recomendado para administradores.
          </p>
          <div className="fila">
            <button className="btn btn-primario" type="button" disabled={iniciar.isPending}
              onClick={() => iniciar.mutate()}>Activar 2FA</button>
          </div>
        </>
      )}
      {error && <div className="alerta-error">{error}</div>}
    </section>
  )
}

function Sesiones() {
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: ['mis-sesiones'],
    queryFn: async () => (await api.get<SesionActiva[]>('/auth/sesiones')).data,
  })
  const cerrar = useMutation({
    mutationFn: (id: string) => api.delete(`/auth/sesiones/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['mis-sesiones'] }),
  })

  return (
    <section className="form-finanzas form-alta">
      <h3>Sesiones abiertas</h3>
      <table className="tabla">
        <thead>
          <tr><th>Equipo</th><th>IP</th><th>Inicio</th><th>Último uso</th><th></th></tr>
        </thead>
        <tbody>
          {data?.map((s) => (
            <tr key={s.id}>
              <td>{resumirAgente(s.user_agent)} {s.actual && <span className="etiqueta etiqueta-activa">Esta</span>}</td>
              <td className="mono">{s.ip ?? '—'}</td>
              <td>{fechaHoraLegible(s.creada_at)}</td>
              <td>{fechaHoraLegible(s.ultimo_uso_at)}</td>
              <td>
                {!s.actual && (
                  <button className="btn btn-chico btn-secundario" onClick={() => cerrar.mutate(s.id)}>
                    Cerrar
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

function resumirAgente(ua: string | null): string {
  if (!ua) return 'Desconocido'
  const nav = /Edg\//.test(ua) ? 'Edge' : /Chrome\//.test(ua) ? 'Chrome' : /Firefox\//.test(ua) ? 'Firefox'
    : /Safari\//.test(ua) ? 'Safari' : 'Navegador'
  const so = /Windows/.test(ua) ? 'Windows' : /Android/.test(ua) ? 'Android' : /iPhone|iPad/.test(ua) ? 'iOS'
    : /Mac OS/.test(ua) ? 'macOS' : /Linux/.test(ua) ? 'Linux' : ''
  return `${nav}${so ? ` en ${so}` : ''}`
}

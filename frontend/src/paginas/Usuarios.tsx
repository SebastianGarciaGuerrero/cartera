import { useState } from 'react'
import type { FormEvent } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, mensajeDeError } from '../api/client'
import type { Usuario, Rol, Cliente } from '../api/tipos'
import { fechaHoraLegible } from '../componentes/utiles'

// Gestión de usuarios (solo admin): crear cuentas del equipo (por invitación
// al correo, sin que el admin conozca la clave), cambiar rol, activar o
// desactivar, desbloquear cuentas y reiniciar el 2FA de quien perdió el
// teléfono. El rol "mandante" es para el portal de clientes.

export default function Usuarios() {
  const qc = useQueryClient()
  const [editando, setEditando] = useState<Usuario | null>(null)
  const [reseteando, setReseteando] = useState<Usuario | null>(null)
  const [aviso, setAviso] = useState('')

  const { data: usuarios, isLoading } = useQuery({
    queryKey: ['usuarios'],
    queryFn: async () => (await api.get<Usuario[]>('/usuarios/')).data,
  })
  const { data: roles } = useQuery({
    queryKey: ['roles'],
    queryFn: async () => (await api.get<Rol[]>('/usuarios/roles')).data,
  })

  const nombreRol = (rol_id: number) =>
    roles?.find((r) => r.id === rol_id)?.nombre ?? `rol ${rol_id}`

  function refrescar() {
    qc.invalidateQueries({ queryKey: ['usuarios'] })
  }

  const accion = useMutation({
    mutationFn: async ({ u, ruta }: { u: Usuario; ruta: string }) => {
      await api.post(`/usuarios/${u.id}/${ruta}`)
      return { u, ruta }
    },
    onSuccess: ({ u, ruta }) => {
      setAviso(ruta === 'invitar' ? `Se envió un enlace de acceso a ${u.email}.`
        : ruta === 'desbloquear' ? `${u.nombre} ya puede volver a intentar.`
        : `2FA de ${u.nombre} reiniciado: deberá configurarlo de nuevo.`)
      refrescar()
    },
    onError: (err) => setAviso(mensajeDeError(err)),
  })

  return (
    <>
      <header className="pagina-cabecera">
        <h1>Usuarios</h1>
      </header>

      <div className="alta-zona">
        <NuevoUsuario roles={roles ?? []} alCrear={refrescar} />
      </div>

      {aviso && <div className="alerta-exito">{aviso}</div>}

      {isLoading ? (
        <div className="pantalla-carga">Cargando usuarios…</div>
      ) : (
        <table className="tabla">
          <thead>
            <tr>
              <th>Nombre</th><th>Email</th><th>Rol</th>
              <th>Estado</th><th>Último acceso</th><th></th>
            </tr>
          </thead>
          <tbody>
            {usuarios?.map((u) => (
              <tr key={u.id}>
                <td className="negrita">{u.nombre}</td>
                <td>{u.email}</td>
                <td>{nombreRol(u.rol_id)}</td>
                <td>
                  {u.activo
                    ? <span className="etiqueta etiqueta-pagada">Activo</span>
                    : <span className="etiqueta etiqueta-archivada">Inactivo</span>}
                  {u.bloqueado && <span className="etiqueta etiqueta-castigo">Bloqueado</span>}
                  {u.mfa_activo && <span className="etiqueta etiqueta-activa">2FA</span>}
                </td>
                <td className="suave">{u.ultimo_acceso ? fechaHoraLegible(u.ultimo_acceso) : '—'}</td>
                <td className="acciones-fila">
                  <button className="btn btn-chico btn-secundario" onClick={() => setEditando(u)}>
                    Editar
                  </button>
                  <button className="btn btn-chico btn-secundario"
                    onClick={() => accion.mutate({ u, ruta: 'invitar' })}>
                    Enviar enlace de acceso
                  </button>
                  <button className="btn btn-chico btn-secundario" onClick={() => setReseteando(u)}>
                    Clave temporal
                  </button>
                  {u.bloqueado && (
                    <button className="btn btn-chico btn-secundario"
                      onClick={() => accion.mutate({ u, ruta: 'desbloquear' })}>
                      Desbloquear
                    </button>
                  )}
                  {u.mfa_activo && (
                    <button className="btn btn-chico btn-secundario"
                      onClick={() => {
                        if (confirm(`¿Quitar el 2FA de ${u.nombre}?`)) accion.mutate({ u, ruta: 'reiniciar-2fa' })
                      }}>
                      Reiniciar 2FA
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {editando && (
        <EditarUsuario
          usuario={editando}
          roles={roles ?? []}
          alCerrar={() => setEditando(null)}
          alGuardar={() => { setEditando(null); refrescar() }}
        />
      )}
      {reseteando && (
        <ClaveTemporal
          usuario={reseteando}
          alCerrar={() => setReseteando(null)}
        />
      )}
    </>
  )
}

// ------------------------------------------------------------

function SelectorCliente({ valor, alCambiar }: { valor: string; alCambiar: (v: string) => void }) {
  const { data: clientes } = useQuery({
    queryKey: ['clientes'],
    queryFn: async () => (await api.get<Cliente[]>('/clientes/')).data,
  })
  return (
    <label>
      Cliente que verá en el portal *
      <select value={valor} onChange={(e) => alCambiar(e.target.value)} required>
        <option value="">Seleccionar…</option>
        {clientes?.map((c) => (
          <option key={c.id} value={c.id}>{c.nombre_fantasia ?? c.razon_social}</option>
        ))}
      </select>
    </label>
  )
}

function NuevoUsuario({ roles, alCrear }: { roles: Rol[]; alCrear: () => void }) {
  const [abierto, setAbierto] = useState(false)
  const [nombre, setNombre] = useState('')
  const [email, setEmail] = useState('')
  const [rolId, setRolId] = useState('')
  const [clienteId, setClienteId] = useState('')
  const [conClave, setConClave] = useState(false)
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [resultado, setResultado] = useState('')
  const esMandante = roles.find((r) => String(r.id) === rolId)?.nombre === 'mandante'

  const crear = useMutation({
    mutationFn: async () => {
      const r = await api.post('/usuarios/', {
        nombre, email, rol_id: Number(rolId),
        password: conClave ? password : null,
        cliente_id: esMandante ? clienteId : null,
      })
      return r.headers['x-invitacion-enviada'] as string | undefined
    },
    onSuccess: (invitacion) => {
      setResultado(
        conClave
          ? 'Usuario creado. Entrégale la clave temporal: deberá cambiarla al entrar.'
          : invitacion === '1'
            ? `Usuario creado. Le enviamos a ${email} un enlace para elegir su contraseña.`
            : 'Usuario creado, pero el correo no salió (revisa la configuración de correo). Usa "Enviar enlace de acceso" más tarde.',
      )
      setNombre(''); setEmail(''); setPassword(''); setRolId(''); setClienteId(''); setError('')
      setAbierto(false)
      alCrear()
    },
    onError: (err) => setError(mensajeDeError(err)),
  })

  if (!abierto) {
    return (
      <>
        {resultado && <div className="alerta-exito">{resultado}</div>}
        <button className="btn btn-primario" onClick={() => { setResultado(''); setAbierto(true) }}>
          + Nuevo usuario
        </button>
      </>
    )
  }

  function alEnviar(e: FormEvent) {
    e.preventDefault()
    setError('')
    crear.mutate()
  }

  return (
    <form className="form-finanzas form-alta" onSubmit={alEnviar}>
      <h3>Nuevo usuario</h3>
      <div className="fila">
        <label>
          Nombre *
          <input value={nombre} onChange={(e) => setNombre(e.target.value)} required />
        </label>
        <label>
          Email *
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)}
            placeholder="persona@empresa.cl" required />
        </label>
      </div>
      <div className="fila">
        <label>
          Rol *
          <select value={rolId} onChange={(e) => setRolId(e.target.value)} required>
            <option value="">Seleccionar…</option>
            {roles.map((r) => (
              <option key={r.id} value={r.id} title={r.descripcion ?? ''}>{r.nombre}</option>
            ))}
          </select>
        </label>
        {esMandante && <SelectorCliente valor={clienteId} alCambiar={setClienteId} />}
      </div>
      <label className="check">
        <input type="checkbox" checked={conClave} onChange={(e) => setConClave(e.target.checked)} />
        Asignar una clave temporal en vez de enviar una invitación por correo
      </label>
      {conClave && (
        <label>
          Clave temporal (mín. 12 caracteres)
          <input value={password} onChange={(e) => setPassword(e.target.value)} minLength={12} required />
        </label>
      )}
      <p className="nota">
        {conClave
          ? 'La persona deberá cambiarla en su primer ingreso.'
          : 'Le llegará un correo con un enlace (válido 3 días) para que elija su propia contraseña.'}
      </p>
      {error && <div className="alerta-error">{error}</div>}
      <div className="fila">
        <button className="btn btn-primario" disabled={crear.isPending}>
          {crear.isPending ? 'Creando…' : 'Crear usuario'}
        </button>
        <button type="button" className="btn btn-secundario" onClick={() => setAbierto(false)}>
          Cancelar
        </button>
      </div>
    </form>
  )
}

// ------------------------------------------------------------

function EditarUsuario({ usuario, roles, alCerrar, alGuardar }: {
  usuario: Usuario; roles: Rol[]; alCerrar: () => void; alGuardar: () => void
}) {
  const [nombre, setNombre] = useState(usuario.nombre)
  const [email, setEmail] = useState(usuario.email)
  const [rolId, setRolId] = useState(String(usuario.rol_id))
  const [clienteId, setClienteId] = useState(usuario.cliente_id ?? '')
  const [activo, setActivo] = useState(usuario.activo)
  const [error, setError] = useState('')
  const esMandante = roles.find((r) => String(r.id) === rolId)?.nombre === 'mandante'

  const guardar = useMutation({
    mutationFn: async () => {
      await api.put(`/usuarios/${usuario.id}`, {
        nombre, email, rol_id: Number(rolId), activo,
        cliente_id: esMandante ? clienteId : null,
      })
    },
    onSuccess: alGuardar,
    onError: (err) => setError(mensajeDeError(err)),
  })

  return (
    <div className="modal-fondo" onClick={alCerrar}>
      <form className="modal" onClick={(e) => e.stopPropagation()}
        onSubmit={(e) => { e.preventDefault(); setError(''); guardar.mutate() }}>
        <h3>Editar usuario</h3>
        <label>
          Nombre
          <input value={nombre} onChange={(e) => setNombre(e.target.value)} required />
        </label>
        <label>
          Email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <label>
          Rol
          <select value={rolId} onChange={(e) => setRolId(e.target.value)}>
            {roles.map((r) => (
              <option key={r.id} value={r.id}>{r.nombre}</option>
            ))}
          </select>
        </label>
        {esMandante && <SelectorCliente valor={clienteId} alCambiar={setClienteId} />}
        <label className="check">
          <input type="checkbox" checked={activo} onChange={(e) => setActivo(e.target.checked)} />
          Usuario activo (puede iniciar sesión)
        </label>
        <p className="nota">Desactivar o cambiar el rol cierra sus sesiones abiertas.</p>
        {error && <div className="alerta-error">{error}</div>}
        <div className="fila">
          <button className="btn btn-primario" disabled={guardar.isPending}>
            {guardar.isPending ? 'Guardando…' : 'Guardar cambios'}
          </button>
          <button type="button" className="btn btn-secundario" onClick={alCerrar}>
            Cancelar
          </button>
        </div>
      </form>
    </div>
  )
}

// ------------------------------------------------------------

function ClaveTemporal({ usuario, alCerrar }: { usuario: Usuario; alCerrar: () => void }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [listo, setListo] = useState(false)

  const resetear = useMutation({
    mutationFn: async () => {
      await api.put(`/usuarios/${usuario.id}/password`, { password_nueva: password })
    },
    onSuccess: () => setListo(true),
    onError: (err) => setError(mensajeDeError(err)),
  })

  return (
    <div className="modal-fondo" onClick={alCerrar}>
      <form className="modal" onClick={(e) => e.stopPropagation()}
        onSubmit={(e) => { e.preventDefault(); setError(''); resetear.mutate() }}>
        <h3>Clave temporal</h3>
        {listo ? (
          <>
            <div className="alerta-exito">
              Clave temporal de <strong>{usuario.nombre}</strong> lista: entrégasela en persona.
              Sus sesiones abiertas se cerraron y deberá cambiarla al entrar.
            </div>
            <button type="button" className="btn btn-primario" onClick={alCerrar}>Cerrar</button>
          </>
        ) : (
          <>
            <p className="suave">
              Clave temporal para <strong>{usuario.nombre}</strong> ({usuario.email}).
              Mejor alternativa: "Enviar enlace de acceso", así tú no conoces su clave.
            </p>
            <label>
              Clave temporal
              <input value={password} onChange={(e) => setPassword(e.target.value)}
                minLength={12} placeholder="mínimo 12 caracteres" required autoFocus />
            </label>
            {error && <div className="alerta-error">{error}</div>}
            <div className="fila">
              <button className="btn btn-primario" disabled={resetear.isPending}>
                {resetear.isPending ? 'Guardando…' : 'Fijar clave temporal'}
              </button>
              <button type="button" className="btn btn-secundario" onClick={alCerrar}>
                Cancelar
              </button>
            </div>
          </>
        )}
      </form>
    </div>
  )
}

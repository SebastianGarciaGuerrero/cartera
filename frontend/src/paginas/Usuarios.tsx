import { useState } from 'react'
import type { FormEvent } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, mensajeDeError } from '../api/client'
import type { Usuario, Rol } from '../api/tipos'
import { fechaHoraLegible } from '../componentes/utiles'

// Gestión de usuarios (solo admin): crear cuentas del equipo, cambiar rol,
// activar/desactivar y resetear contraseñas. Reemplaza tener que pedir cada
// usuario por API.

export default function Usuarios() {
  const qc = useQueryClient()
  const [editando, setEditando] = useState<Usuario | null>(null)
  const [reseteando, setReseteando] = useState<Usuario | null>(null)

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

  return (
    <>
      <header className="pagina-cabecera">
        <h1>Usuarios</h1>
      </header>

      <div className="alta-zona">
        <NuevoUsuario roles={roles ?? []} alCrear={refrescar} />
      </div>

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
                </td>
                <td className="suave">{u.ultimo_acceso ? fechaHoraLegible(u.ultimo_acceso) : '—'}</td>
                <td className="acciones-fila">
                  <button className="btn btn-chico btn-secundario" onClick={() => setEditando(u)}>
                    Editar
                  </button>
                  <button className="btn btn-chico btn-secundario" onClick={() => setReseteando(u)}>
                    Resetear clave
                  </button>
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
        <ResetearClave
          usuario={reseteando}
          alCerrar={() => setReseteando(null)}
        />
      )}
    </>
  )
}

// ------------------------------------------------------------

function NuevoUsuario({ roles, alCrear }: { roles: Rol[]; alCrear: () => void }) {
  const [abierto, setAbierto] = useState(false)
  const [nombre, setNombre] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [rolId, setRolId] = useState('')
  const [error, setError] = useState('')

  const crear = useMutation({
    mutationFn: async () => {
      await api.post('/usuarios/', {
        nombre, email, password, rol_id: Number(rolId),
      })
    },
    onSuccess: () => {
      setNombre(''); setEmail(''); setPassword(''); setRolId(''); setError('')
      setAbierto(false)
      alCrear()
    },
    onError: (err) => setError(mensajeDeError(err)),
  })

  if (!abierto) {
    return (
      <button className="btn btn-primario" onClick={() => setAbierto(true)}>
        + Nuevo usuario
      </button>
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
          Contraseña inicial *
          <input value={password} onChange={(e) => setPassword(e.target.value)}
            minLength={8} placeholder="mínimo 8 caracteres" required />
        </label>
        <label>
          Rol *
          <select value={rolId} onChange={(e) => setRolId(e.target.value)} required>
            <option value="">Seleccionar…</option>
            {roles.map((r) => (
              <option key={r.id} value={r.id}>{r.nombre}</option>
            ))}
          </select>
        </label>
      </div>
      <p className="nota">
        La contraseña inicial se la entregas tú a la persona; ella puede cambiarla después.
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
  const [activo, setActivo] = useState(usuario.activo)
  const [error, setError] = useState('')

  const guardar = useMutation({
    mutationFn: async () => {
      await api.put(`/usuarios/${usuario.id}`, {
        nombre, email, rol_id: Number(rolId), activo,
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
        <label className="check">
          <input type="checkbox" checked={activo} onChange={(e) => setActivo(e.target.checked)} />
          Usuario activo (puede iniciar sesión)
        </label>
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

function ResetearClave({ usuario, alCerrar }: { usuario: Usuario; alCerrar: () => void }) {
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
        <h3>Resetear contraseña</h3>
        {listo ? (
          <>
            <div className="alerta-exito">
              Contraseña de <strong>{usuario.nombre}</strong> cambiada. Entrégasela en persona.
            </div>
            <button type="button" className="btn btn-primario" onClick={alCerrar}>Cerrar</button>
          </>
        ) : (
          <>
            <p className="suave">
              Nueva contraseña para <strong>{usuario.nombre}</strong> ({usuario.email}).
            </p>
            <label>
              Nueva contraseña
              <input value={password} onChange={(e) => setPassword(e.target.value)}
                minLength={8} placeholder="mínimo 8 caracteres" required autoFocus />
            </label>
            {error && <div className="alerta-error">{error}</div>}
            <div className="fila">
              <button className="btn btn-primario" disabled={resetear.isPending}>
                {resetear.isPending ? 'Cambiando…' : 'Cambiar contraseña'}
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

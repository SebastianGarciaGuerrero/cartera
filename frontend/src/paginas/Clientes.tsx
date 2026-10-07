import { Fragment, useState } from 'react'
import type { FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, mensajeDeError } from '../api/client'
import { useAuth } from '../auth'
import type { Cliente, Filial } from '../api/tipos'

// Mandantes (clientes) del estudio: quienes entregan cartera para cobrar.
// Cada uno con sus filiales/sucursales y, si el deudor le paga directo a
// él, sus propios datos de transferencia (salen en el mensaje de pago).

interface ClienteCompleto extends Cliente {
  direccion: string | null
  comuna: string | null
  ciudad: string | null
  telefono: string | null
  email: string | null
  activo: boolean
}

export default function Clientes() {
  const { etiqueta, esAdmin, usuario } = useAuth()
  const puedeEditar = esAdmin || usuario?.rol === 'supervisor'
  const [verInactivos, setVerInactivos] = useState(false)
  const [editando, setEditando] = useState<ClienteCompleto | 'nuevo' | null>(null)
  const [abierto, setAbierto] = useState<string | null>(null)

  const { data: clientes, isLoading } = useQuery({
    queryKey: ['clientes', 'admin', verInactivos],
    queryFn: async () => (await api.get<ClienteCompleto[]>('/clientes/', {
      params: { solo_activos: !verInactivos, limit: 500 },
    })).data,
  })

  const plural = etiqueta('clientes', 'Clientes')
  const singular = etiqueta('cliente', 'Cliente')

  return (
    <>
      <header className="pagina-cabecera">
        <h1>{plural}</h1>
        {puedeEditar && (
          <button className="btn btn-primario" onClick={() => setEditando('nuevo')}>
            + Nuevo {singular.toLowerCase()}
          </button>
        )}
      </header>
      <label className="check">
        <input type="checkbox" checked={verInactivos} onChange={(e) => setVerInactivos(e.target.checked)} />
        Mostrar también los desactivados
      </label>

      {isLoading ? <div className="pantalla-carga">Cargando…</div> : (
        <table className="tabla">
          <thead>
            <tr><th>{singular}</th><th>RUT</th><th>Contacto</th><th>Datos de pago propios</th><th></th></tr>
          </thead>
          <tbody>
            {clientes?.map((c) => (
              <Fragment key={c.id}>
                <tr className={c.activo ? '' : 'suave'}>
                  <td className="negrita">{c.nombre_fantasia ?? c.razon_social}
                    {c.nombre_fantasia && <div className="suave">{c.razon_social}</div>}
                  </td>
                  <td className="mono">{c.rut}</td>
                  <td>{[c.email, c.telefono].filter(Boolean).join(' · ') || '—'}</td>
                  <td>{c.instrucciones_pago ? 'Sí' : <span className="suave">Usa los del estudio</span>}</td>
                  <td className="acciones-fila">
                    <button className="btn btn-chico btn-secundario"
                      onClick={() => setAbierto(abierto === c.id ? null : c.id)}>
                      {etiqueta('filiales', 'Filiales')}
                    </button>
                    {puedeEditar && (
                      <button className="btn btn-chico btn-secundario" onClick={() => setEditando(c)}>Editar</button>
                    )}
                  </td>
                </tr>
                {abierto === c.id && (
                  <tr><td colSpan={5}><Filiales clienteId={c.id} puedeEditar={puedeEditar} /></td></tr>
                )}
              </Fragment>
            ))}
            {clientes?.length === 0 && (
              <tr><td colSpan={5} className="vacio">Todavía no hay {plural.toLowerCase()}. Crea el primero para empezar a cargar cobranzas.</td></tr>
            )}
          </tbody>
        </table>
      )}

      {editando && (
        <FormCliente cliente={editando === 'nuevo' ? null : editando} alCerrar={() => setEditando(null)} />
      )}
    </>
  )
}

function FormCliente({ cliente, alCerrar }: { cliente: ClienteCompleto | null; alCerrar: () => void }) {
  const qc = useQueryClient()
  const { etiqueta } = useAuth()
  const [f, setF] = useState({
    rut: cliente?.rut ?? '',
    razon_social: cliente?.razon_social ?? '',
    nombre_fantasia: cliente?.nombre_fantasia ?? '',
    email: cliente?.email ?? '',
    telefono: cliente?.telefono ?? '',
    direccion: cliente?.direccion ?? '',
    comuna: cliente?.comuna ?? '',
    ciudad: cliente?.ciudad ?? '',
    instrucciones_pago: cliente?.instrucciones_pago ?? '',
    activo: cliente?.activo ?? true,
  })
  const [error, setError] = useState('')
  const campo = (k: keyof typeof f) => ({
    value: f[k] as string,
    onChange: (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value })),
  })

  const guardar = useMutation({
    mutationFn: async () => {
      const vacioANull = (v: string) => (v.trim() === '' ? null : v.trim())
      const cuerpo = {
        razon_social: f.razon_social.trim(),
        nombre_fantasia: vacioANull(f.nombre_fantasia),
        email: vacioANull(f.email), telefono: vacioANull(f.telefono),
        direccion: vacioANull(f.direccion), comuna: vacioANull(f.comuna), ciudad: vacioANull(f.ciudad),
        instrucciones_pago: vacioANull(f.instrucciones_pago),
      }
      if (cliente) await api.put(`/clientes/${cliente.id}`, { ...cuerpo, activo: f.activo })
      else await api.post('/clientes/', { ...cuerpo, rut: f.rut })
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['clientes'] }); alCerrar() },
    onError: (err) => setError(mensajeDeError(err)),
  })

  return (
    <div className="modal-fondo" onClick={alCerrar}>
      <form className="modal modal-ancho" onClick={(e) => e.stopPropagation()}
        onSubmit={(e: FormEvent) => { e.preventDefault(); setError(''); guardar.mutate() }}>
        <h3>{cliente ? 'Editar' : 'Nuevo'} {etiqueta('cliente', 'Cliente').toLowerCase()}</h3>
        <div className="fila">
          <label>RUT *
            <input {...campo('rut')} disabled={Boolean(cliente)} required placeholder="76.123.456-7" />
          </label>
          <label>Razón social *
            <input {...campo('razon_social')} required maxLength={200} />
          </label>
          <label>Nombre de fantasía
            <input {...campo('nombre_fantasia')} maxLength={200} />
          </label>
        </div>
        <div className="fila">
          <label>Email <input type="email" {...campo('email')} /></label>
          <label>Teléfono <input {...campo('telefono')} /></label>
        </div>
        <div className="fila">
          <label>Dirección <input {...campo('direccion')} /></label>
          <label>Comuna <input {...campo('comuna')} /></label>
          <label>Ciudad <input {...campo('ciudad')} /></label>
        </div>
        <label>
          Datos de transferencia propios (solo si el deudor le paga directo a este {etiqueta('cliente', 'cliente').toLowerCase()})
          <textarea rows={4} {...campo('instrucciones_pago')}
            placeholder={'Banco Estado, cuenta corriente N° 123456\nRUT 76.123.456-7\ncobranza@cliente.cl'} />
        </label>
        {cliente && (
          <label className="check">
            <input type="checkbox" checked={f.activo} onChange={(e) => setF((x) => ({ ...x, activo: e.target.checked }))} />
            Activo
          </label>
        )}
        {error && <div className="alerta-error">{error}</div>}
        <div className="fila">
          <button className="btn btn-primario" disabled={guardar.isPending}>Guardar</button>
          <button type="button" className="btn btn-secundario" onClick={alCerrar}>Cancelar</button>
        </div>
      </form>
    </div>
  )
}

function Filiales({ clienteId, puedeEditar }: { clienteId: string; puedeEditar: boolean }) {
  const qc = useQueryClient()
  const { etiqueta } = useAuth()
  const [nombre, setNombre] = useState('')
  const [error, setError] = useState('')
  const { data: filiales } = useQuery({
    queryKey: ['filiales', clienteId, 'todas'],
    queryFn: async () => (await api.get<Filial[]>('/filiales/', {
      params: { cliente_id: clienteId, solo_activas: false },
    })).data,
  })
  const refrescar = () => qc.invalidateQueries({ queryKey: ['filiales'] })
  const crear = useMutation({
    mutationFn: () => api.post('/filiales/', { cliente_id: clienteId, nombre }),
    onSuccess: () => { setNombre(''); setError(''); refrescar() },
    onError: (err) => setError(mensajeDeError(err)),
  })
  const alternar = useMutation({
    mutationFn: (f: Filial) => api.put(`/filiales/${f.id}`, { activo: !f.activo }),
    onSuccess: refrescar,
  })

  return (
    <div>
      {filiales?.length === 0 && <p className="suave">Sin {etiqueta('filiales', 'filiales').toLowerCase()}.</p>}
      <ul className="lista-tipos">
        {filiales?.map((f) => (
          <li key={f.id} className={f.activo ? '' : 'suave'}>
            {f.nombre}
            {puedeEditar && (
              <button className="btn btn-chico btn-secundario" onClick={() => alternar.mutate(f)}>
                {f.activo ? 'Desactivar' : 'Activar'}
              </button>
            )}
          </li>
        ))}
      </ul>
      {puedeEditar && (
        <form className="fila" onSubmit={(e: FormEvent) => { e.preventDefault(); crear.mutate() }}>
          <input value={nombre} onChange={(e) => setNombre(e.target.value)} required maxLength={100}
            placeholder={`Nueva ${etiqueta('filial', 'filial').toLowerCase()}`} />
          <button className="btn btn-chico btn-primario" disabled={crear.isPending}>Agregar</button>
          {error && <span className="alerta-error">{error}</span>}
        </form>
      )}
    </div>
  )
}

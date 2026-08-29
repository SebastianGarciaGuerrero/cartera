import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Cobranza, Cliente, EstadoCobranza } from '../api/tipos'
import { EtiquetaEstado, Plata } from '../componentes/utiles'

const ESTADOS: EstadoCobranza[] = [
  'activa', 'acuerdo_pago', 'judicial', 'pagada', 'archivada', 'castigo',
]

const POR_PAGINA = 20

export default function Cobranzas() {
  const [busqueda, setBusqueda] = useState('')
  const [estado, setEstado] = useState('')
  const [clienteId, setClienteId] = useState('')
  const [pagina, setPagina] = useState(0)

  const { data: clientes } = useQuery({
    queryKey: ['clientes'],
    queryFn: async () => (await api.get<Cliente[]>('/clientes/')).data,
  })

  // Si hay texto de búsqueda usa /buscar (resultados acotados); si no, lista
  // paginada del servidor (de a POR_PAGINA, con el total en un header).
  const { data, isLoading } = useQuery({
    queryKey: ['cobranzas', busqueda, estado, clienteId, pagina],
    queryFn: async () => {
      if (busqueda.trim()) {
        const res = await api.get<Cobranza[]>('/cobranzas/buscar', {
          params: { q: busqueda.trim() },
        })
        return { items: res.data, total: res.data.length, buscando: true }
      }
      const params: Record<string, string> = {
        skip: String(pagina * POR_PAGINA), limit: String(POR_PAGINA),
      }
      if (estado) params.estado = estado
      if (clienteId) params.cliente_id = clienteId
      const res = await api.get<Cobranza[]>('/cobranzas/', { params })
      const total = Number(res.headers['x-total-count'] ?? res.data.length)
      return { items: res.data, total, buscando: false }
    },
  })

  const cobranzas = data?.items
  const total = data?.total ?? 0
  const buscando = data?.buscando ?? false
  const totalPaginas = Math.max(1, Math.ceil(total / POR_PAGINA))

  return (
    <>
      <header className="pagina-cabecera">
        <h1>Cobranzas</h1>
      </header>

      <div className="filtros">
        <input
          className="buscador"
          placeholder="Buscar por N° de cobranza, ID cliente, RUT o nombre del deudor…"
          value={busqueda}
          onChange={(e) => { setBusqueda(e.target.value); setPagina(0) }}
        />
        <select value={estado} onChange={(e) => { setEstado(e.target.value); setPagina(0) }}>
          <option value="">Todos los estados</option>
          {ESTADOS.map((e) => (
            <option key={e} value={e}>{e.replace('_', ' ')}</option>
          ))}
        </select>
        <select value={clienteId} onChange={(e) => { setClienteId(e.target.value); setPagina(0) }}>
          <option value="">Todos los clientes</option>
          {clientes?.map((c) => (
            <option key={c.id} value={c.id}>
              {c.nombre_fantasia ?? c.razon_social}
            </option>
          ))}
        </select>
      </div>

      {isLoading ? (
        <div className="pantalla-carga">Cargando cobranzas…</div>
      ) : (
        <table className="tabla">
          <thead>
            <tr>
              <th>N° Cobranza</th>
              <th>ID cliente</th>
              <th>Estado</th>
              <th className="der">Deuda original</th>
              <th className="der">Saldo actual</th>
              <th>Ingreso</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {cobranzas?.map((c) => (
              <tr key={c.id}>
                <td className="mono negrita">{c.numero}</td>
                <td className="mono">{c.id_externo ?? '—'}</td>
                <td><EtiquetaEstado estado={c.estado} /></td>
                <td className="der"><Plata valor={c.monto_original} /></td>
                <td className="der"><Plata valor={c.monto_actual} /></td>
                <td>{c.fecha_ingreso ?? '—'}</td>
                <td>
                  <Link className="btn btn-chico btn-secundario" to={`/cobranzas/${c.id}`}>
                    Ver ficha
                  </Link>
                </td>
              </tr>
            ))}
            {cobranzas?.length === 0 && (
              <tr><td colSpan={7} className="vacio">Sin resultados</td></tr>
            )}
          </tbody>
        </table>
      )}

      {!buscando && total > POR_PAGINA && (
        <div className="paginacion">
          <button
            className="btn btn-chico btn-secundario"
            disabled={pagina === 0}
            onClick={() => setPagina((p) => Math.max(0, p - 1))}
          >
            ← Anterior
          </button>
          <span className="suave">
            Página {pagina + 1} de {totalPaginas} · {total} cobranzas
          </span>
          <button
            className="btn btn-chico btn-secundario"
            disabled={pagina + 1 >= totalPaginas}
            onClick={() => setPagina((p) => p + 1)}
          >
            Siguiente →
          </button>
        </div>
      )}
    </>
  )
}

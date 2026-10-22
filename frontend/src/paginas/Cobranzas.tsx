import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { useAuth } from '../auth'
import type { Cobranza, Cliente, EstadoCobranza } from '../api/tipos'
import { EtiquetaEstado, Plata, compacto, fechaLegible } from '../componentes/utiles'

const ESTADOS: EstadoCobranza[] = [
  'activa', 'acuerdo_pago', 'judicial', 'pagada', 'archivada', 'castigo',
]

const POR_PAGINA = 20

// Etapas del ciclo de vida para el tablero de arriba (como un embudo).
const ETAPAS: [string, string][] = [
  ['ingreso', 'Ingreso'], ['extrajudicial', 'Extrajudicial'], ['para_demanda', 'Para demanda'],
  ['judicial', 'Judicial'], ['termino', 'Terminadas'],
]
const NOMBRE_ETAPA: Record<string, string> = Object.fromEntries(ETAPAS)

interface ResumenEtapa { etapa: string; cantidad: number; saldo: string }

export default function Cobranzas() {
  const { etiqueta } = useAuth()
  const [busqueda, setBusqueda] = useState('')
  const [estado, setEstado] = useState('')
  const [clienteId, setClienteId] = useState('')
  const [etapa, setEtapa] = useState('')
  const [saldoMin, setSaldoMin] = useState('')
  const [saldoMax, setSaldoMax] = useState('')
  const [pagina, setPagina] = useState(0)

  const { data: clientes } = useQuery({
    queryKey: ['clientes'],
    queryFn: async () => (await api.get<Cliente[]>('/clientes/')).data,
  })

  const { data: etapas } = useQuery({
    queryKey: ['cobranzas', 'etapas', clienteId],
    queryFn: async () => (await api.get<ResumenEtapa[]>('/cobranzas/resumen-etapas', {
      params: { cliente_id: clienteId || undefined },
    })).data,
  })

  // Si hay texto de búsqueda usa /buscar (resultados acotados); si no, lista
  // paginada del servidor (de a POR_PAGINA, con el total en un header).
  const { data, isLoading } = useQuery({
    queryKey: ['cobranzas', busqueda, estado, clienteId, etapa, saldoMin, saldoMax, pagina],
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
      if (etapa) params.etapa = etapa
      if (saldoMin) params.saldo_min = saldoMin
      if (saldoMax) params.saldo_max = saldoMax
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

      <div className="tablero-etapas" role="group" aria-label="Cartera por etapa">
        {ETAPAS.map(([clave, nombre]) => {
          const e = etapas?.find((x) => x.etapa === clave)
          return (
            <button key={clave} className={`tablero-etapa${etapa === clave ? ' elegida' : ''}`} aria-pressed={etapa === clave}
              onClick={() => { setEtapa(etapa === clave ? '' : clave); setPagina(0) }}>
              <span className="suave">{nombre}</span>
              <strong>{e?.cantidad ?? '—'}</strong>
              <span className="suave">{e && clave !== 'termino' ? compacto(Number(e.saldo)) : e ? 'cerradas' : ''}</span>
            </button>
          )
        })}
      </div>

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
        <div className="filtro-saldo">
          <input type="number" min="0" placeholder="Saldo mín." value={saldoMin} aria-label="Saldo mínimo"
            onChange={(e) => { setSaldoMin(e.target.value); setPagina(0) }} />
          <input type="number" min="0" placeholder="Saldo máx." value={saldoMax} aria-label="Saldo máximo"
            onChange={(e) => { setSaldoMax(e.target.value); setPagina(0) }} />
        </div>
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
              <th>N°</th>
              <th>Deudor</th>
              <th>{etiqueta('cliente', 'Cliente')}</th>
              <th>Etapa</th>
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
                <td>
                  {c.deudor_nombre}
                  <div className="mono suave">{c.deudor_rut}{c.id_externo ? ` · ${etiqueta('id_externo', 'ID')} ${c.id_externo}` : ''}</div>
                </td>
                <td>{c.cliente_nombre}</td>
                <td className="suave">{['pagada', 'archivada', 'castigo'].includes(c.estado) ? 'Terminada' : NOMBRE_ETAPA[c.etapa ?? ''] ?? '—'}</td>
                <td><EtiquetaEstado estado={c.estado} /></td>
                <td className="der"><Plata valor={c.monto_original} /></td>
                <td className="der"><Plata valor={c.monto_actual} /></td>
                <td>{fechaLegible(c.fecha_ingreso)}</td>
                <td>
                  <Link className="btn btn-chico btn-secundario" to={`/cobranzas/${c.id}`}>
                    Ver ficha
                  </Link>
                </td>
              </tr>
            ))}
            {cobranzas?.length === 0 && (
              <tr><td colSpan={9} className="vacio">Sin resultados</td></tr>
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

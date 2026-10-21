import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, mensajeDeError } from '../api/client'
import type { Gasto, Rendicion, RendicionDetalle, ResumenGastosCliente } from '../api/judicial'
import { Plata, clp, fechaLegible, fechaLocal } from '../componentes/utiles'
import { useCatalogos } from '../componentes/usarJudicial'

// Gastos que pone el estudio (receptor, notificaciones, embargos…) y que el
// mandante devuelve. Por rendir → rendido (va en una rendición) → reembolsado.

const ETIQUETA_RENDICION: Record<Rendicion['estado'], string> = {
  enviada: 'Por pagar', pagada: 'Pagada', anulada: 'Anulada',
}

export default function Gastos() {
  const [params, setParams] = useSearchParams()
  const qc = useQueryClient()
  const { data: catalogos } = useCatalogos()
  const clienteId = params.get('cliente') ?? ''
  const estado = params.get('estado') ?? 'por_rendir'
  const [elegidos, setElegidos] = useState<string[]>([])
  const [detalle, setDetalle] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [aviso, setAviso] = useState('')

  function cambiar(clave: string, valor: string) {
    const nuevos = new URLSearchParams(params)
    if (valor) nuevos.set(clave, valor)
    else nuevos.delete(clave)
    setParams(nuevos)
    setElegidos([])
  }

  const { data: resumen } = useQuery({
    queryKey: ['gastos', 'resumen'],
    queryFn: async () => (await api.get<ResumenGastosCliente[]>('/gastos/resumen')).data,
  })
  const { data: gastos, isLoading } = useQuery({
    queryKey: ['gastos', 'lista', clienteId, estado],
    queryFn: async () => (await api.get<Gasto[]>('/gastos/', {
      params: { cliente_id: clienteId || undefined, estado: estado === 'todos' ? undefined : estado, limit: 1000 },
    })).data,
  })
  const { data: rendiciones } = useQuery({
    queryKey: ['gastos', 'rendiciones', clienteId],
    queryFn: async () => (await api.get<Rendicion[]>('/gastos/rendiciones', {
      params: { cliente_id: clienteId || undefined },
    })).data,
  })

  const refrescar = () => { setElegidos([]); qc.invalidateQueries({ queryKey: ['gastos'] }); qc.invalidateQueries({ queryKey: ['judicial'] }) }
  const alError = (e: unknown) => { setAviso(''); setError(mensajeDeError(e)) }

  const rendir = useMutation({
    mutationFn: async () => (await api.post<RendicionDetalle>('/gastos/rendiciones', { gasto_ids: elegidos })).data,
    onSuccess: (r) => { setError(''); setAviso(`Rendición N° ${r.numero} por ${clp(Number(r.total))} emitida.`); refrescar(); setDetalle(r.id) },
    onError: alError,
  })
  const reembolsar = useMutation({
    mutationFn: () => api.post('/gastos/reembolsar', { gasto_ids: elegidos, fecha: fechaLocal() }),
    onSuccess: () => { setError(''); setAviso('Gastos marcados como reembolsados.'); refrescar() },
    onError: alError,
  })
  const pagarRendicion = useMutation({
    mutationFn: (id: string) => api.post(`/gastos/rendiciones/${id}/pagada`, { fecha_pago: fechaLocal() }),
    onSuccess: () => { setError(''); setAviso('Rendición pagada: sus gastos quedaron reembolsados.'); refrescar() },
    onError: alError,
  })
  const anularRendicion = useMutation({
    mutationFn: (id: string) => api.post(`/gastos/rendiciones/${id}/anular`),
    onSuccess: () => { setError(''); setAviso('Rendición anulada: sus gastos volvieron a por rendir.'); refrescar() },
    onError: alError,
  })

  const lista = gastos ?? []
  const seleccion = lista.filter((g) => elegidos.includes(g.id))
  const totalSeleccion = seleccion.reduce((s, g) => s + Number(g.monto), 0)
  const clientesSeleccion = new Set(seleccion.map((g) => g.cliente_id))
  const seleccionables = lista.filter((g) => g.estado === 'por_rendir' || g.estado === 'rendido')

  return (
    <>
      <header className="pagina-cabecera">
        <h1>Gastos por cliente</h1>
        <p className="suave">Lo que el estudio pagó por los casos y cada cliente debe devolver.</p>
      </header>

      <section className="tarjeta">
        <h2>Resumen por cliente</h2>
        <table className="tabla">
          <thead>
            <tr><th>Cliente</th><th className="der">Por rendir</th><th className="der">Rendido sin pagar</th>
              <th className="der">Total adeudado</th><th className="der">Reembolsado</th><th></th></tr>
          </thead>
          <tbody>
            {resumen?.map((r) => (
              <tr key={r.cliente_id} className={r.cliente_id === clienteId ? 'fila-activa' : ''}>
                <td>{r.cliente}</td>
                <td className="der"><Plata valor={r.por_rendir} /> <span className="suave">({r.cantidad_por_rendir})</span></td>
                <td className="der"><Plata valor={r.rendido} /></td>
                <td className="der negrita"><Plata valor={r.total_adeudado} /></td>
                <td className="der suave"><Plata valor={r.reembolsado} /></td>
                <td><button className="btn btn-chico btn-secundario" onClick={() => cambiar('cliente', r.cliente_id)}>Ver gastos</button></td>
              </tr>
            ))}
            {resumen?.length === 0 && <tr><td colSpan={6} className="vacio">Aún no hay gastos registrados.</td></tr>}
          </tbody>
        </table>
      </section>

      <section className="tarjeta separado">
        <div className="tarjeta-cabecera">
          <h2>Gastos</h2>
          <div className="filtros sin-margen">
            <select value={clienteId} onChange={(e) => cambiar('cliente', e.target.value)}>
              <option value="">Todos los clientes</option>
              {resumen?.map((r) => <option key={r.cliente_id} value={r.cliente_id}>{r.cliente}</option>)}
            </select>
            <select value={estado} onChange={(e) => cambiar('estado', e.target.value)}>
              <option value="por_rendir">Por rendir</option>
              <option value="rendido">Rendidos sin pagar</option>
              <option value="adeudado">Adeudados (por rendir + rendidos)</option>
              <option value="reembolsado">Reembolsados</option>
              <option value="no_reembolsable">No reembolsables</option>
              <option value="todos">Todos</option>
            </select>
          </div>
        </div>

        {error && <div className="alerta-error">{error}</div>}
        {aviso && !error && <div className="alerta-exito">{aviso}</div>}

        {elegidos.length > 0 && (
          <div className="barra-seleccion">
            <span><strong>{elegidos.length}</strong> gasto{elegidos.length === 1 ? '' : 's'} · {clp(totalSeleccion)}</span>
            <button className="btn btn-chico btn-primario"
              disabled={rendir.isPending || clientesSeleccion.size !== 1 || seleccion.some((g) => g.estado !== 'por_rendir')}
              title={clientesSeleccion.size !== 1 ? 'Una rendición es de un solo cliente' : undefined}
              onClick={() => rendir.mutate()}>Rendir al cliente</button>
            <button className="btn btn-chico btn-secundario" disabled={reembolsar.isPending}
              onClick={() => reembolsar.mutate()}>Marcar reembolsados</button>
            <button className="btn-texto" onClick={() => setElegidos([])}>Quitar selección</button>
          </div>
        )}

        {isLoading ? <div className="pantalla-carga">Cargando gastos…</div> : (
          <div className="tabla-desplazable">
            <table className="tabla">
              <thead>
                <tr>
                  <th>
                    <input type="checkbox" aria-label="Elegir todos"
                      checked={seleccionables.length > 0 && seleccionables.every((g) => elegidos.includes(g.id))}
                      onChange={(e) => setElegidos(e.target.checked ? seleccionables.map((g) => g.id) : [])} />
                  </th>
                  <th>Fecha</th><th>Cliente</th><th>Caso</th><th>Concepto</th><th>Proveedor</th>
                  <th className="der">Monto</th><th>Estado</th>
                </tr>
              </thead>
              <tbody>
                {lista.map((g) => (
                  <tr key={g.id}>
                    <td>
                      {(g.estado === 'por_rendir' || g.estado === 'rendido') && (
                        <input type="checkbox" checked={elegidos.includes(g.id)}
                          onChange={(e) => setElegidos((x) => e.target.checked ? [...x, g.id] : x.filter((i) => i !== g.id))} />
                      )}
                    </td>
                    <td>{fechaLegible(g.fecha)}</td>
                    <td>{g.cliente_nombre}</td>
                    <td>
                      {g.causa_id && <Link to={`/judicial/causas/${g.causa_id}`}>Rol {g.rol_causa ?? 's/n'}</Link>}
                      {g.cobranza_id && <Link to={`/cobranzas/${g.cobranza_id}`}>N° {g.numero_cobranza}</Link>}
                    </td>
                    <td>{g.concepto}<div className="suave">{catalogos?.tipos_gasto[g.tipo] ?? g.tipo}</div></td>
                    <td>{g.proveedor ?? '—'}{g.numero_boleta && <div className="suave">Boleta {g.numero_boleta}</div>}</td>
                    <td className="der"><Plata valor={g.monto} /></td>
                    <td>
                      <span className={`etiqueta gasto-${g.estado}`}>{catalogos?.estados_gasto[g.estado] ?? g.estado}</span>
                      {g.numero_rendicion && <div className="suave">Rendición N° {g.numero_rendicion}</div>}
                    </td>
                  </tr>
                ))}
                {lista.length === 0 && <tr><td colSpan={8} className="vacio">No hay gastos con estos filtros.</td></tr>}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="tarjeta separado">
        <h2>Rendiciones</h2>
        <table className="tabla">
          <thead><tr><th>N°</th><th>Cliente</th><th>Fecha</th><th className="der">Total</th><th>Gastos</th><th>Estado</th><th></th></tr></thead>
          <tbody>
            {rendiciones?.map((r) => (
              <tr key={r.id}>
                <td className="mono negrita">{r.numero}</td>
                <td>{r.cliente_nombre}</td>
                <td>{fechaLegible(r.fecha)}</td>
                <td className="der"><Plata valor={r.total} /></td>
                <td>{r.cantidad}</td>
                <td>
                  <span className={`etiqueta rendicion-${r.estado}`}>{ETIQUETA_RENDICION[r.estado]}</span>
                  {r.fecha_pago && <div className="suave">{fechaLegible(r.fecha_pago)}</div>}
                </td>
                <td className="acciones-fila">
                  <button className="btn btn-chico btn-secundario" onClick={() => setDetalle(r.id)}>Ver</button>
                  {r.estado === 'enviada' && (
                    <>
                      <button className="btn btn-chico btn-primario" disabled={pagarRendicion.isPending}
                        onClick={() => pagarRendicion.mutate(r.id)}>Marcar pagada</button>
                      <button className="btn btn-chico btn-secundario" disabled={anularRendicion.isPending}
                        onClick={() => { if (window.confirm(`¿Anular la rendición N° ${r.numero}? Sus gastos vuelven a por rendir.`)) anularRendicion.mutate(r.id) }}>
                        Anular
                      </button>
                    </>
                  )}
                </td>
              </tr>
            ))}
            {rendiciones?.length === 0 && <tr><td colSpan={7} className="vacio">Aún no hay rendiciones.</td></tr>}
          </tbody>
        </table>
      </section>

      {detalle && <DetalleRendicion id={detalle} alCerrar={() => setDetalle(null)} />}
    </>
  )
}

function DetalleRendicion({ id, alCerrar }: { id: string; alCerrar: () => void }) {
  const { data: r } = useQuery({
    queryKey: ['gastos', 'rendicion', id],
    queryFn: async () => (await api.get<RendicionDetalle>(`/gastos/rendiciones/${id}`)).data,
  })
  return (
    <div className="modal-fondo" onClick={alCerrar}>
      <div className="modal modal-ancho rendicion-imprimible" onClick={(e) => e.stopPropagation()}>
        {!r ? <p className="suave">Cargando…</p> : (
          <>
            <h3>Rendición de gastos N° {r.numero}</h3>
            <p>
              <strong>{r.cliente_nombre}</strong> · {fechaLegible(r.fecha)} · {ETIQUETA_RENDICION[r.estado]}
              {r.fecha_pago && ` el ${fechaLegible(r.fecha_pago)}`}
            </p>
            <table className="tabla">
              <thead><tr><th>Fecha</th><th>Caso</th><th>Concepto</th><th>Proveedor</th><th className="der">Monto</th></tr></thead>
              <tbody>
                {r.gastos.map((g) => (
                  <tr key={g.id}>
                    <td>{fechaLegible(g.fecha)}</td>
                    <td>{g.rol_causa ? `Rol ${g.rol_causa}` : g.numero_cobranza ? `N° ${g.numero_cobranza}` : '—'}</td>
                    <td>{g.concepto}</td>
                    <td>{g.proveedor ?? '—'}{g.numero_boleta && ` · boleta ${g.numero_boleta}`}</td>
                    <td className="der"><Plata valor={g.monto} /></td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr><td colSpan={4} className="der negrita">Total</td><td className="der negrita"><Plata valor={r.total} /></td></tr>
              </tfoot>
            </table>
            {r.observaciones && <p className="observaciones">{r.observaciones}</p>}
            <div className="acciones-fila no-imprimir">
              <button className="btn btn-primario" onClick={() => window.print()}>Imprimir o guardar PDF</button>
              <button className="btn btn-secundario" onClick={alCerrar}>Cerrar</button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

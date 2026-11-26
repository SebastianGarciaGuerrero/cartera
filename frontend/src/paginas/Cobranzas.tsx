import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, mensajeDeError } from '../api/client'
import { useAuth } from '../auth'
import type { Cobranza, Cliente, EstadoCobranza, ResultadoMasivo } from '../api/tipos'
import { EtiquetaEstado, NOMBRE_ESTADO, Plata, compacto, fechaLegible } from '../componentes/utiles'

const ESTADOS: EstadoCobranza[] = [
  'activa', 'acuerdo_pago', 'judicial', 'pagada', 'archivada', 'castigo', 'eliminada',
]
const TERMINADAS: EstadoCobranza[] = ['pagada', 'archivada', 'castigo', 'eliminada']

const POR_PAGINA = 20

// Etapas del ciclo de vida para el tablero de arriba (como un embudo).
const ETAPAS: [string, string][] = [
  ['ingreso', 'Ingreso'], ['extrajudicial', 'Extrajudicial'], ['para_demanda', 'Para demanda'],
  ['judicial', 'Judicial'], ['termino', 'Terminadas'],
]
const NOMBRE_ETAPA: Record<string, string> = Object.fromEntries(ETAPAS)

interface ResumenEtapa { etapa: string; cantidad: number; saldo: string }
interface Ejecutivo { id: string; nombre: string; rol: string | null; abiertas: number }

export default function Cobranzas() {
  const { etiqueta, puede } = useAuth()
  // El tablero por etapa muestra totales de toda la cartera: solo con permiso.
  const totales = puede('ver_totales')
  const gestionaCartera = puede('cartera_gestionar')
  const [busqueda, setBusqueda] = useState('')
  const [estado, setEstado] = useState('')
  const [clienteId, setClienteId] = useState('')
  const [ejecutivo, setEjecutivo] = useState('')   // '' | 'sin' | id
  const [etapa, setEtapa] = useState('')
  const [saldoMin, setSaldoMin] = useState('')
  const [saldoMax, setSaldoMax] = useState('')
  const [pagina, setPagina] = useState(0)
  // Selección: las marcadas a mano, o "todas las del filtro" (aunque estén en otras páginas).
  const [marcadas, setMarcadas] = useState<Set<string>>(new Set())
  const [todasDelFiltro, setTodasDelFiltro] = useState(false)
  const [accion, setAccion] = useState<'asignar' | 'eliminar' | null>(null)

  const { data: clientes } = useQuery({
    queryKey: ['clientes'],
    queryFn: async () => (await api.get<Cliente[]>('/clientes/')).data,
  })
  const { data: ejecutivos } = useQuery({
    queryKey: ['cartera-ejecutivos'],
    enabled: gestionaCartera,
    queryFn: async () => (await api.get<Ejecutivo[]>('/cartera/ejecutivos')).data,
  })

  const { data: etapas } = useQuery({
    queryKey: ['cobranzas', 'etapas', clienteId],
    enabled: totales,
    queryFn: async () => (await api.get<ResumenEtapa[]>('/cobranzas/resumen-etapas', {
      params: { cliente_id: clienteId || undefined },
    })).data,
  })

  // El mismo filtro sirve para la lista y para "todas las del filtro".
  const filtro: Record<string, string | boolean> = {}
  if (estado) filtro.estado = estado
  if (clienteId) filtro.cliente_id = clienteId
  if (etapa && etapa !== 'termino') filtro.etapa = etapa
  if (ejecutivo === 'sin') filtro.sin_ejecutivo = true
  else if (ejecutivo) filtro.ejecutivo_id = ejecutivo
  if (saldoMin) filtro.saldo_min = saldoMin
  if (saldoMax) filtro.saldo_max = saldoMax

  // Si hay texto de búsqueda usa /buscar (resultados acotados); si no, lista
  // paginada del servidor (de a POR_PAGINA, con el total en un header).
  const { data, isLoading } = useQuery({
    queryKey: ['cobranzas', busqueda, estado, clienteId, etapa, ejecutivo, saldoMin, saldoMax, pagina],
    queryFn: async () => {
      if (busqueda.trim()) {
        const res = await api.get<Cobranza[]>('/cobranzas/buscar', { params: { q: busqueda.trim() } })
        return { items: res.data, total: res.data.length, buscando: true }
      }
      const params = { ...filtro, skip: String(pagina * POR_PAGINA), limit: String(POR_PAGINA),
        ...(etapa === 'termino' ? { etapa } : {}) }
      const res = await api.get<Cobranza[]>('/cobranzas/', { params })
      const total = Number(res.headers['x-total-count'] ?? res.data.length)
      return { items: res.data, total, buscando: false }
    },
  })

  const cobranzas = data?.items
  const total = data?.total ?? 0
  const buscando = data?.buscando ?? false
  const totalPaginas = Math.max(1, Math.ceil(total / POR_PAGINA))
  const filtroAplicable = !buscando && etapa !== 'termino'
  const cantidad = todasDelFiltro ? total : marcadas.size

  function limpiarSeleccion() { setMarcadas(new Set()); setTodasDelFiltro(false) }
  function cambiarFiltro<T>(set: (v: T) => void) {
    return (v: T) => { set(v); setPagina(0); limpiarSeleccion() }
  }
  function marcar(id: string) {
    setTodasDelFiltro(false)
    const nuevo = new Set(marcadas)
    if (nuevo.has(id)) nuevo.delete(id)
    else nuevo.add(id)
    setMarcadas(nuevo)
  }
  const paginaMarcada = Boolean(cobranzas?.length) && cobranzas!.every((c) => marcadas.has(c.id))
  function marcarPagina() {
    setTodasDelFiltro(false)
    const nuevo = new Set(marcadas)
    for (const c of cobranzas ?? []) {
      if (paginaMarcada) nuevo.delete(c.id)
      else nuevo.add(c.id)
    }
    setMarcadas(nuevo)
  }
  const seleccion = todasDelFiltro ? { filtro } : { cobranza_ids: [...marcadas] }

  return (
    <>
      <header className="pagina-cabecera">
        <h1>Cobranzas</h1>
      </header>

      {totales && (
        <div className="tablero-etapas" role="group" aria-label="Cartera por etapa">
          {ETAPAS.map(([clave, nombre]) => {
            const e = etapas?.find((x) => x.etapa === clave)
            return (
              <button key={clave} className={`tablero-etapa${etapa === clave ? ' elegida' : ''}`} aria-pressed={etapa === clave}
                onClick={() => cambiarFiltro(setEtapa)(etapa === clave ? '' : clave)}>
                <span className="suave">{nombre}</span>
                <strong>{e?.cantidad ?? '—'}</strong>
                <span className="suave">{e && clave !== 'termino' ? compacto(Number(e.saldo)) : e ? 'cerradas' : ''}</span>
              </button>
            )
          })}
        </div>
      )}

      <div className="filtros">
        <input
          className="buscador"
          placeholder="Buscar por N° de cobranza, ID cliente, RUT o nombre del deudor…"
          value={busqueda}
          onChange={(e) => cambiarFiltro(setBusqueda)(e.target.value)}
        />
        <select value={estado} onChange={(e) => cambiarFiltro(setEstado)(e.target.value)}>
          <option value="">Todos los estados</option>
          {ESTADOS.map((e) => <option key={e} value={e}>{NOMBRE_ESTADO[e]}</option>)}
        </select>
        <div className="filtro-saldo">
          <input type="number" min="0" placeholder="Saldo mín." value={saldoMin} aria-label="Saldo mínimo"
            onChange={(e) => cambiarFiltro(setSaldoMin)(e.target.value)} />
          <input type="number" min="0" placeholder="Saldo máx." value={saldoMax} aria-label="Saldo máximo"
            onChange={(e) => cambiarFiltro(setSaldoMax)(e.target.value)} />
        </div>
        <select value={clienteId} onChange={(e) => cambiarFiltro(setClienteId)(e.target.value)}>
          <option value="">Todos los clientes</option>
          {clientes?.map((c) => (
            <option key={c.id} value={c.id}>{c.nombre_fantasia ?? c.razon_social}</option>
          ))}
        </select>
        {gestionaCartera && (
          <select value={ejecutivo} onChange={(e) => cambiarFiltro(setEjecutivo)(e.target.value)} aria-label="Ejecutivo">
            <option value="">Todos los ejecutivos</option>
            <option value="sin">Sin asignar</option>
            {ejecutivos?.map((u) => <option key={u.id} value={u.id}>{u.nombre} ({u.abiertas})</option>)}
          </select>
        )}
      </div>

      {gestionaCartera && cantidad > 0 && (
        <div className="barra-cartera" role="region" aria-label="Acciones sobre la selección">
          <strong>{cantidad.toLocaleString('es-CL')} seleccionada{cantidad === 1 ? '' : 's'}</strong>
          {!todasDelFiltro && paginaMarcada && filtroAplicable && total > marcadas.size && (
            <button className="btn-enlace" onClick={() => setTodasDelFiltro(true)}>
              Seleccionar las {total.toLocaleString('es-CL')} del filtro
            </button>
          )}
          <span className="barra-cartera-acciones">
            <button className="btn btn-chico btn-primario" onClick={() => setAccion('asignar')}>Asignar / repartir</button>
            <button className="btn btn-chico btn-peligro" onClick={() => setAccion('eliminar')}>Eliminar de cartera</button>
            <button className="btn btn-chico btn-secundario" onClick={limpiarSeleccion}>Quitar selección</button>
          </span>
        </div>
      )}

      {isLoading ? (
        <div className="pantalla-carga">Cargando cobranzas…</div>
      ) : (
        <div className="tabla-desplazable">
          <table className="tabla">
            <thead>
              <tr>
                {gestionaCartera && (
                  <th className="col-check">
                    <input type="checkbox" checked={paginaMarcada} onChange={marcarPagina}
                      aria-label="Seleccionar las de esta página" />
                  </th>
                )}
                <th>N°</th>
                <th>Deudor</th>
                <th>{etiqueta('cliente', 'Cliente')}</th>
                <th>Ejecutivo</th>
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
                <tr key={c.id} className={marcadas.has(c.id) || todasDelFiltro ? 'fila-marcada' : ''}>
                  {gestionaCartera && (
                    <td className="col-check">
                      <input type="checkbox" checked={todasDelFiltro || marcadas.has(c.id)} onChange={() => marcar(c.id)}
                        aria-label={`Seleccionar cobranza ${c.numero}`} />
                    </td>
                  )}
                  <td className="mono negrita">{c.numero}</td>
                  <td>
                    {c.deudor_nombre}
                    <div className="mono suave">{c.deudor_rut}{c.id_externo ? ` · ${etiqueta('id_externo', 'ID')} ${c.id_externo}` : ''}</div>
                  </td>
                  <td>
                    {c.cliente_nombre}
                    {c.filial_nombre && <div className="suave">{c.filial_nombre}</div>}
                  </td>
                  <td>{c.ejecutivo_nombre ?? <span className="suave">Sin asignar</span>}</td>
                  <td className="suave">{TERMINADAS.includes(c.estado) ? 'Terminada' : NOMBRE_ETAPA[c.etapa ?? ''] ?? '—'}</td>
                  <td><EtiquetaEstado estado={c.estado} /></td>
                  <td className="der"><Plata valor={c.monto_original} /></td>
                  <td className="der"><Plata valor={c.monto_actual} /></td>
                  <td>{fechaLegible(c.fecha_ingreso)}</td>
                  <td>
                    <Link className="btn btn-chico btn-secundario" to={`/cobranzas/${c.id}`}>Ver ficha</Link>
                  </td>
                </tr>
              ))}
              {cobranzas?.length === 0 && (
                <tr><td colSpan={11} className="vacio">Sin resultados</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {!buscando && total > POR_PAGINA && (
        <div className="paginacion">
          <button className="btn btn-chico btn-secundario" disabled={pagina === 0}
            onClick={() => setPagina((p) => Math.max(0, p - 1))}>← Anterior</button>
          <span className="suave">Página {pagina + 1} de {totalPaginas} · {total.toLocaleString('es-CL')} cobranzas</span>
          <button className="btn btn-chico btn-secundario" disabled={pagina + 1 >= totalPaginas}
            onClick={() => setPagina((p) => p + 1)}>Siguiente →</button>
        </div>
      )}

      {accion && (
        <AccionMasiva accion={accion} cantidad={cantidad} seleccion={seleccion} ejecutivos={ejecutivos ?? []}
          alCerrar={() => setAccion(null)} alTerminar={() => { setAccion(null); limpiarSeleccion() }} />
      )}
    </>
  )
}

function AccionMasiva({ accion, cantidad, seleccion, ejecutivos, alCerrar, alTerminar }: {
  accion: 'asignar' | 'eliminar'
  cantidad: number
  seleccion: Record<string, unknown>
  ejecutivos: Ejecutivo[]
  alCerrar: () => void
  alTerminar: () => void
}) {
  const qc = useQueryClient()
  const [elegidos, setElegidos] = useState<string[]>([])
  const [motivo, setMotivo] = useState('')
  const [error, setError] = useState('')
  const [resultado, setResultado] = useState<ResultadoMasivo | null>(null)

  const ejecutar = useMutation({
    mutationFn: async () => (await api.post<ResultadoMasivo>(`/cartera/${accion}`,
      accion === 'asignar' ? { ...seleccion, ejecutivo_ids: elegidos } : { ...seleccion, motivo: motivo.trim() })).data,
    onSuccess: (r) => {
      setResultado(r)
      for (const queryKey of [['cobranzas'], ['cobranza'], ['gestiones'], ['cartera-ejecutivos'], ['agenda'], ['avisos'], ['panel']]) {
        qc.invalidateQueries({ queryKey })
      }
    },
    onError: (e) => setError(mensajeDeError(e)),
  })

  function alternar(id: string) {
    setElegidos(elegidos.includes(id) ? elegidos.filter((x) => x !== id) : [...elegidos, id])
  }
  const porCabeza = elegidos.length > 1 ? Math.ceil(cantidad / elegidos.length) : null

  return (
    <div className="modal-fondo" onClick={resultado ? alTerminar : alCerrar}>
      <form className="modal modal-ancho" role="dialog" onClick={(e) => e.stopPropagation()}
        onSubmit={(e: FormEvent) => { e.preventDefault(); setError(''); ejecutar.mutate() }}>
        <h3>{accion === 'asignar' ? 'Asignar o repartir cartera' : 'Eliminar de cartera'}</h3>
        {resultado ? (
          <>
            <div className="alerta-exito">
              {accion === 'asignar'
                ? `Listo: ${resultado.cambiadas.toLocaleString('es-CL')} cobranza(s) asignada(s).`
                : `Listo: ${resultado.cambiadas.toLocaleString('es-CL')} cobranza(s) eliminada(s) de cartera.`}
              {resultado.omitidas > 0 && ` ${resultado.omitidas.toLocaleString('es-CL')} no cambiaron (cerradas o ya estaban así).`}
            </div>
            {Object.keys(resultado.por_ejecutivo).length > 0 && (
              <ul className="lista-simple">
                {Object.entries(resultado.por_ejecutivo).map(([nombre, n]) => (
                  <li key={nombre}><span>{nombre}</span><strong>{n.toLocaleString('es-CL')}</strong></li>
                ))}
              </ul>
            )}
            <div className="fila"><button type="button" className="btn btn-primario" onClick={alTerminar}>Cerrar</button></div>
          </>
        ) : accion === 'asignar' ? (
          <>
            <p className="suave">
              {cantidad.toLocaleString('es-CL')} cobranza(s). Elige una persona para asignárselas, o varias para
              repartirlas en partes iguales. Solo se asignan las abiertas; cada cambio queda en el historial del caso.
            </p>
            <div className="chips">
              {ejecutivos.map((u) => (
                <button key={u.id} type="button" className={`chip ${elegidos.includes(u.id) ? 'elegido' : ''}`}
                  aria-pressed={elegidos.includes(u.id)} onClick={() => alternar(u.id)}>
                  {u.nombre} <span className="suave">· {u.abiertas} hoy</span>
                </button>
              ))}
            </div>
            {porCabeza && <p className="nota">Quedan unas {porCabeza.toLocaleString('es-CL')} para cada una de las {elegidos.length} personas.</p>}
            {error && <div className="alerta-error">{error}</div>}
            <div className="fila">
              <button className="btn btn-primario" disabled={ejecutar.isPending || elegidos.length === 0}>
                {ejecutar.isPending ? 'Asignando…' : elegidos.length > 1 ? 'Repartir' : 'Asignar'}
              </button>
              <button type="button" className="btn btn-secundario" disabled={ejecutar.isPending} onClick={() => {
                if (confirm('¿Quitar la asignación de estas cobranzas?')) ejecutar.mutate()
              }}>Dejar sin asignar</button>
              <button type="button" className="btn btn-secundario" onClick={alCerrar}>Cancelar</button>
            </div>
          </>
        ) : (
          <>
            <p className="suave">
              El cliente indicó que {cantidad === 1 ? 'esta cobranza ya no corresponde' : `estas ${cantidad.toLocaleString('es-CL')} cobranzas ya no corresponden`}.
              Quedan en el sistema y en los informes como <strong>Eliminada de cartera</strong>; no se borran.
              Solo se eliminan las abiertas.
            </p>
            <label>
              Motivo *
              <textarea rows={3} value={motivo} onChange={(e) => setMotivo(e.target.value)} required minLength={3} maxLength={500}
                placeholder="Ej.: el cliente informa que la deuda fue regularizada en su caja" />
            </label>
            {error && <div className="alerta-error">{error}</div>}
            <div className="fila">
              <button className="btn btn-peligro" disabled={ejecutar.isPending || motivo.trim().length < 3}>
                {ejecutar.isPending ? 'Eliminando…' : `Eliminar ${cantidad.toLocaleString('es-CL')} de cartera`}
              </button>
              <button type="button" className="btn btn-secundario" onClick={alCerrar}>Cancelar</button>
            </div>
          </>
        )}
      </form>
    </div>
  )
}

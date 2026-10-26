import { useState, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, mensajeDeError } from '../api/client'
import type { CausaFila, CobranzaParaDemanda, EtapaProcesal, ResumenJudicial } from '../api/judicial'
import { Plata, fechaLegible, rutConPuntos } from '../componentes/utiles'
import { useConfirmacion } from '../componentes/ConfirmarGestion'
import { clasePlazo, diasHasta, textoPlazo, useCatalogos } from '../componentes/usarJudicial'

// Bandeja judicial: qué causas hay que mover hoy (plazos vencidos y por
// vencer, riesgo de abandono) y qué cobranzas están listas para demandar.

const POR_PAGINA = 25

export default function Judicial() {
  const [params, setParams] = useSearchParams()
  const pestana = params.get('ver') === 'demandar' ? 'demandar' : 'causas'
  const { data: resumen } = useQuery({
    queryKey: ['judicial', 'resumen'],
    queryFn: async () => (await api.get<ResumenJudicial>('/judicial/resumen')).data,
  })

  function filtrarPlazo(plazo: string) {
    setParams({ plazo })
  }

  return (
    <>
      <header className="pagina-cabecera">
        <h1>Judicial</h1>
      </header>

      {resumen && (
        <div className="kpis">
          <button className="kpi kpi-boton" onClick={() => setParams({})}>
            <span className="kpi-titulo">Causas vigentes</span>
            <span className="kpi-valor">{resumen.vigentes}</span>
          </button>
          <button className={`kpi kpi-boton${resumen.plazos_vencidos ? ' kpi-alerta' : ''}`} onClick={() => filtrarPlazo('vencido')}>
            <span className="kpi-titulo">Plazos vencidos</span>
            <span className="kpi-valor">{resumen.plazos_vencidos}</span>
          </button>
          <button className="kpi kpi-boton" onClick={() => filtrarPlazo('semana')}>
            <span className="kpi-titulo">Vencen esta semana</span>
            <span className="kpi-valor">{resumen.plazos_hoy + resumen.plazos_semana}</span>
            <span className="kpi-detalle">{resumen.plazos_hoy} hoy</span>
          </button>
          <button className={`kpi kpi-boton${resumen.riesgo_abandono ? ' kpi-alerta' : ''}`} onClick={() => filtrarPlazo('abandono')}>
            <span className="kpi-titulo">Riesgo de abandono</span>
            <span className="kpi-valor">{resumen.riesgo_abandono}</span>
            <span className="kpi-detalle">5 meses sin trámites</span>
          </button>
          <button className="kpi kpi-boton" onClick={() => setParams({ ver: 'demandar' })}>
            <span className="kpi-titulo">Para demandar</span>
            <span className="kpi-valor">{resumen.para_demanda}</span>
            <span className="kpi-detalle">en preparación</span>
          </button>
        </div>
      )}

      <div className="pestanas">
        <button className={`pestana${pestana === 'causas' ? ' activa' : ''}`} onClick={() => setParams({})}>Causas</button>
        <button className={`pestana${pestana === 'demandar' ? ' activa' : ''}`} onClick={() => setParams({ ver: 'demandar' })}>
          Para demandar
        </button>
      </div>

      {pestana === 'causas' ? <ListaCausas resumen={resumen} /> : <ParaDemandar />}
    </>
  )
}

function ListaCausas({ resumen }: { resumen?: ResumenJudicial }) {
  const [params, setParams] = useSearchParams()
  const { data: catalogos } = useCatalogos()
  const [busqueda, setBusqueda] = useState('')
  const [pagina, setPagina] = useState(0)
  const etapa = params.get('etapa') ?? ''
  const plazo = params.get('plazo') ?? ''
  const estado = params.get('estado') ?? 'vigente'
  const mias = params.get('mias') === '1'

  function cambiar(clave: string, valor: string) {
    const nuevos = new URLSearchParams(params)
    if (valor) nuevos.set(clave, valor)
    else nuevos.delete(clave)
    setParams(nuevos)
    setPagina(0)
  }

  const { data, isLoading } = useQuery({
    queryKey: ['judicial', 'causas', busqueda, etapa, plazo, estado, mias, pagina],
    queryFn: async () => {
      const r = await api.get<CausaFila[]>('/judicial/causas', {
        params: {
          q: busqueda.trim() || undefined, etapa: etapa || undefined, plazo: plazo || undefined,
          estado, mias: mias || undefined, skip: pagina * POR_PAGINA, limit: POR_PAGINA,
        },
      })
      return { filas: r.data, total: Number(r.headers['x-total-count'] ?? r.data.length) }
    },
  })
  const total = data?.total ?? 0
  const totalPaginas = Math.max(1, Math.ceil(total / POR_PAGINA))

  return (
    <>
      <div className="filtros">
        <input className="buscador" placeholder="Buscar por rol, deudor, RUT o N° de cobranza…"
          value={busqueda} onChange={(e) => { setBusqueda(e.target.value); setPagina(0) }} />
        <select value={etapa} onChange={(e) => cambiar('etapa', e.target.value)}>
          <option value="">Todas las etapas</option>
          {Object.entries(catalogos?.etapas ?? {}).map(([k, v]) => (
            <option key={k} value={k}>{v}{resumen ? ` (${resumen.por_etapa[k as EtapaProcesal] ?? 0})` : ''}</option>
          ))}
        </select>
        <select value={plazo} onChange={(e) => cambiar('plazo', e.target.value)}>
          <option value="">Todos los plazos</option>
          <option value="vencido">Plazo vencido</option>
          <option value="semana">Vence esta semana</option>
          <option value="abandono">Riesgo de abandono</option>
        </select>
        <select value={estado} onChange={(e) => cambiar('estado', e.target.value === 'vigente' ? '' : e.target.value)}>
          <option value="vigente">Vigentes</option>
          <option value="terminada">Terminadas</option>
          <option value="todas">Todas</option>
        </select>
        <label className="check">
          <input type="checkbox" checked={mias} onChange={(e) => cambiar('mias', e.target.checked ? '1' : '')} />
          Solo mis causas
        </label>
      </div>

      {isLoading ? <div className="pantalla-carga">Cargando causas…</div> : (
        <div className="tabla-desplazable">
          <table className="tabla">
            <thead>
              <tr>
                <th>Plazo</th>
                <th>Causa</th>
                <th>Demandado</th>
                <th>Cliente</th>
                <th>Etapa</th>
                <th>Último trámite</th>
                <th>Próximo paso</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {data?.filas.map((c) => (
                <tr key={c.id}>
                  <td>
                    {c.estado === 'vigente' ? (
                      <>
                        <span className={`plazo ${clasePlazo(c.plazo_fecha)}`}>{textoPlazo(c.plazo_fecha)}</span>
                        {c.plazo_fecha && <div className="suave">{fechaLegible(c.plazo_fecha)}</div>}
                      </>
                    ) : <span className="etiqueta etiqueta-archivada">{catalogos?.resultados[c.resultado ?? ''] ?? 'Terminada'}</span>}
                  </td>
                  <td>
                    <span className="mono negrita">{c.rol ?? 'Sin rol'}</span>
                    <div className="suave">{c.tribunal ?? 'Sin tribunal'}</div>
                  </td>
                  <td>
                    {c.deudor}
                    <div className="mono suave">
                      {rutConPuntos(c.deudor_rut)}{c.numeros_cobranza && ` · N° ${c.numeros_cobranza.join(', ')}`}
                    </div>
                  </td>
                  <td>{c.cliente}</td>
                  <td>{catalogos?.etapas[c.etapa_procesal] ?? c.etapa_procesal}</td>
                  <td>
                    {c.ultimo_tramite ?? '—'}
                    {c.ultima_fecha && <div className="suave">{fechaLegible(c.ultima_fecha)} · hace {c.dias_sin_movimiento} días</div>}
                  </td>
                  <td>{c.siguiente_nombre ?? '—'}</td>
                  <td><Link className="btn btn-chico btn-secundario" to={`/judicial/causas/${c.id}`}>Abrir</Link></td>
                </tr>
              ))}
              {data?.filas.length === 0 && <tr><td colSpan={8} className="vacio">No hay causas con estos filtros.</td></tr>}
            </tbody>
          </table>
        </div>
      )}

      {total > POR_PAGINA && (
        <div className="paginacion">
          <button className="btn btn-chico btn-secundario" disabled={pagina === 0}
            onClick={() => setPagina((p) => Math.max(0, p - 1))}>← Anterior</button>
          <span className="suave">Página {pagina + 1} de {totalPaginas} · {total} causas</span>
          <button className="btn btn-chico btn-secundario" disabled={pagina + 1 >= totalPaginas}
            onClick={() => setPagina((p) => p + 1)}>Siguiente →</button>
        </div>
      )}
    </>
  )
}

function ParaDemandar() {
  const qc = useQueryClient()
  const [error, setError] = useState('')
  const { data, isLoading } = useQuery({
    queryKey: ['judicial', 'para-demanda'],
    queryFn: async () => (await api.get<{ preparacion: CobranzaParaDemanda[]; sugeridas: CobranzaParaDemanda[] }>(
      '/judicial/para-demanda')).data,
  })
  const preparar = useMutation({
    mutationFn: (id: string) => api.post(`/cobranzas/${id}/etapa`, {
      etapa: 'para_demanda', motivo: 'Cumple el plazo del cliente para demandar',
    }),
    onSuccess: (_r, id) => {
      setError('')
      qc.invalidateQueries({ queryKey: ['judicial'] })
      qc.invalidateQueries({ queryKey: ['ciclo', id] })
    },
    onError: (e) => setError(mensajeDeError(e)),
  })

  const { pedir, modal } = useConfirmacion()

  if (isLoading || !data) return <div className="pantalla-carga">Cargando…</div>

  return (
    <>
      {modal}
      {error && <div className="alerta-error">{error}</div>}
      <section className="tarjeta">
        <h2>En preparación ({data.preparacion.length})</h2>
        <p className="suave">Cobranzas que el equipo decidió demandar. Desde la ficha se presenta la demanda.</p>
        <TablaDemanda filas={data.preparacion} accion={(c) => (
          <Link className="btn btn-chico btn-primario" to={`/cobranzas/${c.id}`}>Presentar demanda</Link>
        )} />
      </section>

      <section className="tarjeta separado">
        <h2>Sugeridas por el plazo del cliente ({data.sugeridas.length})</h2>
        <p className="suave">
          Siguen en cobranza extrajudicial y ya pasaron los días que el cliente fija para demandar
          (se configura en Clientes). La decisión la toma el equipo.
        </p>
        <TablaDemanda filas={data.sugeridas} accion={(c) => (
          <button className="btn btn-chico btn-secundario" disabled={preparar.isPending}
            onClick={() => pedir({
              titulo: `Preparar la demanda de la cobranza N° ${c.numero}`,
              gestion: `CAMBIO DE ETAPA: ${c.etapa === 'ingreso' ? 'Ingreso' : 'Extrajudicial'} → Para demanda. `
                + 'Motivo: Cumple el plazo del cliente para demandar.',
              confirmar: 'Sí, preparar', accion: () => preparar.mutateAsync(c.id),
            })}>Preparar demanda</button>
        )} />
      </section>
    </>
  )
}

function TablaDemanda({ filas, accion }: {
  filas: CobranzaParaDemanda[]; accion: (c: CobranzaParaDemanda) => ReactNode
}) {
  if (filas.length === 0) return <p className="vacio">No hay cobranzas aquí.</p>
  return (
    <div className="tabla-desplazable">
      <table className="tabla">
        <thead>
          <tr><th>N°</th><th>Deudor</th><th>Cliente</th><th className="der">Saldo</th><th>En cartera</th><th>Prescripción</th><th></th></tr>
        </thead>
        <tbody>
          {filas.map((c) => {
            const dias = diasHasta(c.fecha_prescripcion)
            return (
              <tr key={c.id}>
                <td className="mono negrita"><Link to={`/cobranzas/${c.id}`}>{c.numero}</Link></td>
                <td>{c.deudor}<div className="mono suave">{rutConPuntos(c.deudor_rut)}</div></td>
                <td>{c.cliente}{c.dias_para_demanda != null && <div className="suave">demanda a los {c.dias_para_demanda} días</div>}</td>
                <td className="der"><Plata valor={c.monto_actual} /></td>
                <td>{c.dias_en_cartera} días{c.ultima_gestion && <div className="suave">última gestión {fechaLegible(c.ultima_gestion)}</div>}</td>
                <td>
                  {c.fecha_prescripcion ? (
                    <span className={dias != null && dias <= 90 ? 'texto-rojo' : ''}>{fechaLegible(c.fecha_prescripcion)}</span>
                  ) : <span className="suave">—</span>}
                </td>
                <td>{accion(c)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

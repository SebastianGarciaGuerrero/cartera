import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, descargarArchivo, mensajeDeError } from '../api/client'
import { useAuth } from '../auth'
import type {
  AcuerdoPendiente, CobranzaPortal, EstadoCobranza, FichaPortal, ResumenPortal,
} from '../api/tipos'
import {
  EtiquetaEstado, MESES, MESES_CORTOS, NOMBRE_ESTADO, Plata, clp, compacto, fechaLegible, rutConPuntos,
} from '../componentes/utiles'
import { CLASE_CUOTA, NOMBRE_CUOTA, NOMBRE_FORMA } from '../componentes/Finanzas'

// Portal de clientes (rol 'mandante'): lo que el cliente del estudio ve de
// su propia cartera. Todo sale de /api/portal, que filtra por su cliente.

// ------------------------------------------------------------ resumen

export function PortalResumen() {
  const { data: r, isLoading } = useQuery({
    queryKey: ['portal', 'resumen'],
    queryFn: async () => (await api.get<ResumenPortal>('/portal/resumen')).data,
  })
  if (isLoading || !r) return <div className="pantalla-carga">Cargando…</div>

  const recuperado = Number(r.recuperado_total)
  const asignado = Number(r.asignado)
  const pct = asignado > 0 ? recuperado / asignado : null

  return (
    <>
      <header className="pagina-cabecera">
        <h1>{r.cliente}</h1>
        <p className="suave">Cartera en gestión con {r.estudio}</p>
      </header>

      {r.acuerdos_por_aprobar > 0 && (
        <div className="aviso">
          <span>
            <strong>{r.acuerdos_por_aprobar} {r.acuerdos_por_aprobar === 1 ? 'acuerdo espera' : 'acuerdos esperan'}</strong>{' '}
            tu aprobación.
          </span>
          <Link className="btn btn-chico btn-primario" to="/portal/acuerdos">Revisar</Link>
        </div>
      )}

      <section className="kpis">
        <div className="kpi kpi-hero">
          <span className="kpi-titulo">Capital recuperado</span>
          <span className="kpi-valor">{clp(recuperado)}</span>
          <span className="kpi-detalle">
            {pct !== null ? `${(pct * 100).toLocaleString('es-CL', { maximumFractionDigits: 1 })} % de lo asignado` : 'desde el inicio'}
          </span>
        </div>
        <div className="kpi">
          <span className="kpi-titulo">Saldo en cobranza</span>
          <span className="kpi-valor">{compacto(Number(r.saldo_abierto))}</span>
          <span className="kpi-detalle">{r.casos_abiertos} de {r.casos_totales} casos abiertos</span>
        </div>
        <div className="kpi">
          <span className="kpi-titulo">Recuperado este mes</span>
          <span className="kpi-valor">{compacto(Number(r.recuperado_mes))}</span>
          <span className="kpi-detalle">capital de {MESES[new Date().getMonth()].toLowerCase()}</span>
        </div>
        <div className="kpi">
          <span className="kpi-titulo">Asignado</span>
          <span className="kpi-valor">{compacto(asignado)}</span>
          <span className="kpi-detalle">{r.casos_totales} caso(s) entregados</span>
        </div>
        <div className="kpi">
          <span className="kpi-titulo">Acuerdos vigentes</span>
          <span className="kpi-valor">{r.acuerdos_vigentes}</span>
          <span className="kpi-detalle">{r.acuerdos_por_aprobar} por aprobar</span>
        </div>
      </section>

      <section className="tarjeta">
        <h2>Capital recuperado por mes</h2>
        <GraficoRecupero meses={r.meses} />
      </section>
    </>
  )
}

/** Barra con las esquinas de arriba redondeadas y la base recta. */
function barra(x: number, y: number, ancho: number, alto: number) {
  const r = Math.min(4, ancho / 2, alto)
  return `M${x},${y + alto} V${y + r} Q${x},${y} ${x + r},${y} H${x + ancho - r} Q${x + ancho},${y} ${x + ancho},${y + r} V${y + alto} Z`
}

function GraficoRecupero({ meses }: { meses: ResumenPortal['meses'] }) {
  const [activo, setActivo] = useState<number | null>(null)
  const maximo = Math.max(1, ...meses.map((m) => Number(m.capital)))
  const ancho = 720
  const alto = 220
  const margenIzq = 56
  const altoUtil = alto - 26 - 10
  const paso = (ancho - margenIzq) / meses.length
  const grosor = Math.min(36, paso * 0.6)
  const escala = (v: number) => (v / maximo) * altoUtil
  const base = 10 + altoUtil
  const nombreMes = (iso: string) => `${MESES_CORTOS[Number(iso.slice(5, 7)) - 1]} ${iso.slice(0, 4)}`

  if (meses.every((m) => Number(m.capital) === 0)) {
    return <p className="suave">Todavía no hay pagos registrados en los últimos 12 meses.</p>
  }
  return (
    <div className="grafico">
      <svg viewBox={`0 0 ${ancho} ${alto}`} role="img" aria-label="Capital recuperado por mes, últimos 12 meses">
        {[0, 0.5, 1].map((f) => {
          const y = base - escala(f * maximo)
          return (
            <g key={f}>
              <line x1={margenIzq} x2={ancho} y1={y} y2={y} className="grafico-grilla" />
              <text x={margenIzq - 6} y={y + 4} textAnchor="end" className="grafico-eje">{compacto(f * maximo)}</text>
            </g>
          )
        })}
        {meses.map((m, i) => {
          const x = margenIzq + paso * i + (paso - grosor) / 2
          const h = escala(Number(m.capital))
          return (
            <g key={m.mes} onMouseEnter={() => setActivo(i)} onMouseLeave={() => setActivo(null)}>
              <rect x={margenIzq + paso * i} y={10} width={paso} height={altoUtil} fill="transparent" />
              {h > 0 && <path d={barra(x, base - h, grosor, h)} fill="var(--serie-capital)"
                opacity={activo === null || activo === i ? 1 : 0.45} />}
              <text x={x + grosor / 2} y={alto - 8} textAnchor="middle" className="grafico-eje">
                {MESES_CORTOS[Number(m.mes.slice(5, 7)) - 1]}
              </text>
            </g>
          )
        })}
      </svg>
      {activo !== null && (
        <div className="grafico-tooltip">
          <strong>{nombreMes(meses[activo].mes)}</strong>
          <span>{clp(Number(meses[activo].capital))}</span>
        </div>
      )}
      <details>
        <summary className="suave">Ver como tabla</summary>
        <table className="tabla">
          <thead><tr><th>Mes</th><th className="der">Capital recuperado</th></tr></thead>
          <tbody>
            {meses.map((m) => (
              <tr key={m.mes}><td>{nombreMes(m.mes)}</td><td className="der"><Plata valor={m.capital} /></td></tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  )
}

// ------------------------------------------------------------ cartera

const ESTADOS = Object.keys(NOMBRE_ESTADO) as EstadoCobranza[]
const POR_PAGINA = 25

export function PortalCartera() {
  const { etiqueta } = useAuth()
  const [busqueda, setBusqueda] = useState('')
  const [estado, setEstado] = useState('')
  const [pagina, setPagina] = useState(0)
  const q = busqueda.trim()

  const { data, isLoading } = useQuery({
    queryKey: ['portal', 'cobranzas', q, estado, pagina],
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const params: Record<string, string> = { skip: String(pagina * POR_PAGINA), limit: String(POR_PAGINA) }
      if (q) params.q = q
      if (estado) params.estado = estado
      const res = await api.get<CobranzaPortal[]>('/portal/cobranzas', { params })
      return { items: res.data, total: Number(res.headers['x-total-count'] ?? res.data.length) }
    },
  })
  const total = data?.total ?? 0
  const totalPaginas = Math.max(1, Math.ceil(total / POR_PAGINA))

  return (
    <>
      <header className="pagina-cabecera"><h1>Cartera</h1></header>

      <div className="filtros">
        <input className="buscador" placeholder={`Buscar por nombre, RUT o ${etiqueta('id_externo', 'ID cliente')}…`}
          value={busqueda} onChange={(e) => { setBusqueda(e.target.value); setPagina(0) }} />
        <select value={estado} onChange={(e) => { setEstado(e.target.value); setPagina(0) }}>
          <option value="">Todos los estados</option>
          {ESTADOS.map((e) => <option key={e} value={e}>{NOMBRE_ESTADO[e]}</option>)}
        </select>
      </div>

      {isLoading ? <div className="pantalla-carga">Cargando…</div> : (
        <div className="tabla-desplazable">
          <table className="tabla">
            <thead>
              <tr>
                <th>N°</th><th>{etiqueta('deudor', 'Deudor')}</th><th>Estado</th>
                <th className="der">Deuda original</th><th className="der">Saldo</th>
                <th>Última gestión</th><th></th>
              </tr>
            </thead>
            <tbody>
              {data?.items.map((c) => (
                <tr key={c.id}>
                  <td className="mono negrita">{c.numero}</td>
                  <td>
                    <Link to={`/portal/cartera/${c.id}`} className="negrita">{c.deudor}</Link>
                    <div className="mono suave">
                      {rutConPuntos(c.rut)}{c.id_externo ? ` · ${etiqueta('id_externo', 'ID')} ${c.id_externo}` : ''}
                    </div>
                  </td>
                  <td><EtiquetaEstado estado={c.estado} /></td>
                  <td className="der"><Plata valor={c.monto_original} /></td>
                  <td className="der"><Plata valor={c.monto_actual} /></td>
                  <td>{fechaLegible(c.ultima_gestion)}</td>
                  <td><Link className="btn btn-chico btn-secundario" to={`/portal/cartera/${c.id}`}>Ver detalle</Link></td>
                </tr>
              ))}
              {data?.items.length === 0 && <tr><td colSpan={7} className="vacio">Sin resultados.</td></tr>}
            </tbody>
          </table>
        </div>
      )}

      {total > POR_PAGINA && (
        <div className="paginacion">
          <button className="btn btn-chico btn-secundario" disabled={pagina === 0}
            onClick={() => setPagina((p) => Math.max(0, p - 1))}>← Anterior</button>
          <span className="suave">Página {pagina + 1} de {totalPaginas} · {total} casos</span>
          <button className="btn btn-chico btn-secundario" disabled={pagina + 1 >= totalPaginas}
            onClick={() => setPagina((p) => p + 1)}>Siguiente →</button>
        </div>
      )}
    </>
  )
}

// ------------------------------------------------------------ ficha

const NOMBRE_ACUERDO: Record<string, string> = {
  vigente: 'Vigente', cumplido: 'Cumplido', incumplido: 'Incumplido', renegociado: 'Renegociado',
}

export function PortalFicha() {
  const { id } = useParams()
  const { etiqueta } = useAuth()
  const { data: f, isLoading } = useQuery({
    queryKey: ['portal', 'ficha', id],
    queryFn: async () => (await api.get<FichaPortal>(`/portal/cobranzas/${id}`)).data,
  })
  if (isLoading) return <div className="pantalla-carga">Cargando…</div>
  if (!f) return <div className="vacio-busqueda">No encontramos ese caso. <Link to="/portal/cartera">Volver a la cartera</Link></div>

  const recuperado = f.pagos.reduce((s, p) => s + Number(p.capital), 0)
  const a = f.acuerdo

  return (
    <>
      <Link to="/portal/cartera" className="volver">← Cartera</Link>
      <header className="pagina-cabecera">
        <h1>{f.deudor}</h1>
        <p className="suave">
          <span className="mono">{rutConPuntos(f.rut)}</span> · N° {f.numero}
          {f.id_externo && <> · {etiqueta('id_externo', 'ID cliente')} <span className="mono">{f.id_externo}</span></>}
          {' '}<EtiquetaEstado estado={f.estado} />
        </p>
      </header>

      <div className="ficha-grilla ficha-portal">
        <section className="tarjeta">
          <h2>Deuda</h2>
          <dl className="datos">
            <dt>Deuda original</dt><dd><Plata valor={f.monto_original} /></dd>
            <dt>Saldo actual</dt><dd className="negrita"><Plata valor={f.monto_actual} /></dd>
            <dt>Recuperado</dt><dd><Plata valor={recuperado} /> <span className="suave">de capital</span></dd>
            <dt>Ingreso</dt><dd>{fechaLegible(f.fecha_ingreso)}</dd>
          </dl>

          {a && (
            <>
              <h3 className="subtitulo">Acuerdo de pago</h3>
              <p>
                {NOMBRE_ACUERDO[a.estado] ?? a.estado} · {fechaLegible(a.fecha_acuerdo)} · total <Plata valor={a.monto_total_acordado} />
                {Number(a.pie) > 0 && <> (pie <Plata valor={a.pie} />)</>} en {a.numero_cuotas} cuota(s)
                {a.firma_cliente === 'firmado_confirmado'
                  ? <span className="etiqueta etiqueta-pagada">Aprobado</span>
                  : a.estado === 'vigente' && <Link to="/portal/acuerdos" className="etiqueta etiqueta-acuerdo_pago">Por aprobar</Link>}
              </p>
              <div className="tabla-desplazable">
                <table className="tabla tabla-cuotas">
                  <thead><tr><th>Cuota</th><th>Vence</th><th className="der">Monto</th><th className="der">Pagado</th><th>Estado</th></tr></thead>
                  <tbody>
                    {a.cuotas.map((c) => (
                      <tr key={c.id}>
                        <td className="mono">{c.numero_cuota}/{a.numero_cuotas}</td>
                        <td>{fechaLegible(c.fecha_vencimiento)}</td>
                        <td className="der"><Plata valor={c.monto} /></td>
                        <td className="der"><Plata valor={c.monto_pagado} /></td>
                        <td><span className={`etiqueta ${CLASE_CUOTA[c.estado]}`}>{NOMBRE_CUOTA[c.estado]}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          <h3 className="subtitulo">Pagos ({f.pagos.length})</h3>
          {f.pagos.length === 0 ? <p className="suave">Sin pagos registrados.</p> : (
            <div className="tabla-desplazable">
              <table className="tabla">
                <thead><tr><th>Fecha</th><th>Forma</th><th className="der">Monto</th><th className="der">Capital</th></tr></thead>
                <tbody>
                  {f.pagos.map((p, i) => (
                    <tr key={i}>
                      <td>{fechaLegible(p.fecha_pago)}</td>
                      <td>{p.forma_pago ? NOMBRE_FORMA[p.forma_pago] ?? p.forma_pago : '—'}</td>
                      <td className="der"><Plata valor={p.monto} /></td>
                      <td className="der"><Plata valor={p.capital} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="tarjeta">
          <h2>Gestiones ({f.gestiones.length})</h2>
          {f.gestiones.length === 0 ? <p className="suave">Todavía no hay gestiones registradas.</p> : (
            <ul className="linea-tiempo">
              {f.gestiones.map((g, i) => (
                <li key={i}>
                  <div className="gestion-cabecera">
                    <span className="gestion-tipo">{g.tipo ?? 'Gestión'}</span>
                    <span className="suave">{fechaLegible(g.fecha)}</span>
                  </div>
                  <p>{g.descripcion}</p>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </>
  )
}

// ------------------------------------------------------------ acuerdos

export function PortalAcuerdos() {
  const { data: lista, isLoading } = useQuery({
    queryKey: ['portal', 'pendientes'],
    queryFn: async () => (await api.get<AcuerdoPendiente[]>('/portal/acuerdos/pendientes')).data,
  })

  return (
    <>
      <header className="pagina-cabecera">
        <h1>Acuerdos por aprobar</h1>
        <p className="suave">
          Acuerdos de pago negociados con tus deudores. Revisa el documento y apruébalo,
          o indica por qué no lo apruebas: el estudio verá tu respuesta en el caso.
        </p>
      </header>
      {isLoading ? <div className="pantalla-carga">Cargando…</div>
        : lista?.length === 0 ? <div className="vacio-busqueda">No hay acuerdos esperando tu aprobación.</div>
        : <div className="acuerdos-portal">{lista?.map((a) => <TarjetaAcuerdo key={a.id} a={a} />)}</div>}
    </>
  )
}

function TarjetaAcuerdo({ a }: { a: AcuerdoPendiente }) {
  const qc = useQueryClient()
  const [observando, setObservando] = useState(false)
  const [motivo, setMotivo] = useState('')
  const [error, setError] = useState('')
  const refrescar = () => qc.invalidateQueries({ queryKey: ['portal'] })

  const aprobar = useMutation({
    mutationFn: () => api.post(`/portal/acuerdos/${a.id}/aprobar`),
    onSuccess: refrescar,
    onError: (e) => setError(mensajeDeError(e)),
  })
  const observar = useMutation({
    mutationFn: () => api.post(`/portal/acuerdos/${a.id}/observar`, { motivo: motivo.trim() }),
    onSuccess: () => { setObservando(false); setMotivo(''); setError(''); refrescar() },
    onError: (e) => setError(mensajeDeError(e)),
  })

  const total = Number(a.monto_total_acordado)
  const cuota = (total - Number(a.pie)) / Math.max(1, a.numero_cuotas)

  return (
    <section className="tarjeta">
      <div className="ficha-deudor-cabecera">
        <div>
          <h2 className="resumen-titulo">{a.deudor}</h2>
          <Link to={`/portal/cartera/${a.cobranza_id}`} className="suave">Caso N° {a.numero_cobranza}</Link>
        </div>
        <button className="btn btn-chico btn-secundario"
          onClick={() => descargarArchivo(`/portal/acuerdos/${a.id}/documento`)}>Ver documento (Word)</button>
      </div>

      <dl className="datos">
        <dt>Fecha del acuerdo</dt><dd>{fechaLegible(a.fecha_acuerdo)}</dd>
        <dt>Total acordado</dt><dd className="negrita"><Plata valor={total} /></dd>
        {Number(a.pie) > 0 && <><dt>Pie</dt><dd><Plata valor={a.pie} /></dd></>}
        <dt>Cuotas</dt><dd>{a.numero_cuotas} de aprox. {clp(cuota)}</dd>
      </dl>
      {a.observaciones && <p className="observaciones">{a.observaciones}</p>}

      {observando ? (
        <form className="formulario-observacion" onSubmit={(e) => { e.preventDefault(); observar.mutate() }}>
          <label>
            ¿Por qué no lo apruebas?
            <textarea rows={3} value={motivo} onChange={(e) => setMotivo(e.target.value)} required minLength={3}
              maxLength={1000} autoFocus placeholder="Ej.: el pie es muy bajo, pedir al menos el 20 %." />
          </label>
          <div className="acciones-fila">
            <button className="btn btn-primario" disabled={observar.isPending || motivo.trim().length < 3}>Enviar respuesta</button>
            <button type="button" className="btn btn-secundario" onClick={() => setObservando(false)}>Cancelar</button>
          </div>
        </form>
      ) : (
        <div className="acciones-fila separado">
          <button className="btn btn-primario" disabled={aprobar.isPending} onClick={() => {
            if (confirm(`¿Apruebas el acuerdo con ${a.deudor} por ${clp(total)} en ${a.numero_cuotas} cuota(s)?`)) aprobar.mutate()
          }}>Aprobar</button>
          <button className="btn btn-secundario" onClick={() => setObservando(true)}>No aprobar</button>
        </div>
      )}
      {error && <div className="alerta-error">{error}</div>}
    </section>
  )
}

// ------------------------------------------------------------ informes

export function PortalInformes() {
  const hoy = new Date()
  const [mes, setMes] = useState(String(hoy.getMonth() + 1))
  const [anio, setAnio] = useState(String(hoy.getFullYear()))
  const periodo = { mes, anio }

  return (
    <>
      <header className="pagina-cabecera"><h1>Informes</h1></header>
      <div className="filtros">
        <select value={mes} onChange={(e) => setMes(e.target.value)}>
          {MESES.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
        </select>
        <input type="number" className="anio" value={anio} min={2000} max={2100}
          onChange={(e) => setAnio(e.target.value)} />
      </div>
      <div className="informes-grilla">
        <section className="tarjeta">
          <h2>Recupero del mes</h2>
          <p className="suave">Cada pago recibido en el mes, con su desglose de capital, intereses y honorarios.</p>
          <button className="btn btn-primario" onClick={() => descargarArchivo('/portal/exportar/recupero', periodo)}>
            Descargar Excel
          </button>
        </section>
        <section className="tarjeta">
          <h2>Rendición del mes</h2>
          <p className="suave">Lo que corresponde rendirte en el mes (capital e intereses), por sucursal.</p>
          <button className="btn btn-primario" onClick={() => descargarArchivo('/portal/exportar/rendicion', periodo)}>
            Descargar Excel
          </button>
        </section>
      </div>
    </>
  )
}

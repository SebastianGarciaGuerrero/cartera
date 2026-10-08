import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { useAuth } from '../auth'
import type { Cliente, EstadoCobranza, Usuario } from '../api/tipos'
import { EtiquetaEstado, MESES_CORTOS, Plata, clp, compacto, fechaLocal } from '../componentes/utiles'

// Panel de indicadores: cuánto se recuperó, cómo está la cartera y dónde
// hay que poner atención (cuotas atrasadas, casos sin gestión).

interface Recupero { total: string; capital: string; honorarios: string; intereses: string; pagos: number }
interface Mes { mes: string; capital: string; honorarios: string; otros: string; total: string }
interface DatosPanel {
  desde: string
  hasta: string
  recupero: Recupero
  recupero_anterior: Recupero
  cartera: { estado: EstadoCobranza; cantidad: number; saldo: string; original: string }[]
  cuotas_atrasadas: number
  monto_atrasado: string
  cuotas_vencidas_periodo: number
  cuotas_pagadas_periodo: number
  gestiones_periodo: number
  sin_gestion_30_dias: number
  meses: Mes[]
  por_cliente: { cliente_id: string; cliente: string; abiertas: number; saldo: string; asignado: string;
    recuperado_periodo: string; recuperado_total: string }[]
}

type Periodo = 'mes' | 'mes_anterior' | 'trimestre' | 'anio'

function rango(periodo: Periodo): { desde: string; hasta: string } {
  const hoy = new Date()
  const a = hoy.getFullYear()
  const m = hoy.getMonth()
  if (periodo === 'mes_anterior') {
    return { desde: fechaLocal(new Date(a, m - 1, 1)), hasta: fechaLocal(new Date(a, m, 0)) }
  }
  if (periodo === 'trimestre') return { desde: fechaLocal(new Date(a, m - 2, 1)), hasta: fechaLocal(hoy) }
  if (periodo === 'anio') return { desde: fechaLocal(new Date(a, 0, 1)), hasta: fechaLocal(hoy) }
  return { desde: fechaLocal(new Date(a, m, 1)), hasta: fechaLocal(hoy) }
}

export default function PanelIndicadores() {
  const { usuario, etiqueta } = useAuth()
  const veTodo = usuario?.rol === 'admin' || usuario?.rol === 'supervisor'
  const [periodo, setPeriodo] = useState<Periodo>('mes')
  const [clienteId, setClienteId] = useState('')
  const [ejecutivoId, setEjecutivoId] = useState('')
  const { desde, hasta } = rango(periodo)

  const { data: clientes } = useQuery({
    queryKey: ['clientes'],
    queryFn: async () => (await api.get<Cliente[]>('/clientes/')).data,
  })
  const { data: equipo } = useQuery({
    queryKey: ['usuarios'],
    enabled: usuario?.rol === 'admin',
    queryFn: async () => (await api.get<Usuario[]>('/usuarios/')).data,
  })
  const { data: p, isLoading } = useQuery({
    queryKey: ['panel', desde, hasta, clienteId, ejecutivoId],
    queryFn: async () => (await api.get<DatosPanel>('/panel', {
      params: { desde, hasta, ...(clienteId ? { cliente_id: clienteId } : {}),
        ...(ejecutivoId ? { ejecutivo_id: ejecutivoId } : {}) },
    })).data,
  })

  return (
    <>
      <header className="pagina-cabecera"><h1>Panel</h1></header>
      <div className="filtros">
        <select value={periodo} onChange={(e) => setPeriodo(e.target.value as Periodo)}>
          <option value="mes">Este mes</option>
          <option value="mes_anterior">Mes anterior</option>
          <option value="trimestre">Últimos 3 meses</option>
          <option value="anio">Este año</option>
        </select>
        <select value={clienteId} onChange={(e) => setClienteId(e.target.value)}>
          <option value="">Todos los {etiqueta('clientes', 'clientes').toLowerCase()}</option>
          {clientes?.map((c) => <option key={c.id} value={c.id}>{c.nombre_fantasia ?? c.razon_social}</option>)}
        </select>
        {veTodo && equipo && (
          <select value={ejecutivoId} onChange={(e) => setEjecutivoId(e.target.value)}>
            <option value="">Todo el equipo</option>
            {equipo.filter((u) => u.activo).map((u) => <option key={u.id} value={u.id}>{u.nombre}</option>)}
          </select>
        )}
      </div>

      {isLoading || !p ? <div className="pantalla-carga">Calculando…</div> : <Contenido p={p} />}
    </>
  )
}

function Contenido({ p }: { p: DatosPanel }) {
  const { etiqueta } = useAuth()
  const total = Number(p.recupero.total)
  const anterior = Number(p.recupero_anterior.total)
  const variacion = anterior > 0 ? (total - anterior) / anterior : null
  const abiertas = p.cartera.filter((e) => ['activa', 'acuerdo_pago', 'judicial'].includes(e.estado))
  const saldoAbierto = abiertas.reduce((s, e) => s + Number(e.saldo), 0)
  const casosAbiertos = abiertas.reduce((s, e) => s + e.cantidad, 0)
  const cumplimiento = p.cuotas_vencidas_periodo > 0 ? p.cuotas_pagadas_periodo / p.cuotas_vencidas_periodo : null

  return (
    <>
      <section className="kpis">
        <div className="kpi kpi-hero">
          <span className="kpi-titulo">Recuperado en el período</span>
          <span className="kpi-valor">{clp(total)}</span>
          <span className="kpi-detalle">
            {p.recupero.pagos} pago(s)
            {variacion !== null && (
              <> · <span className={variacion >= 0 ? 'kpi-sube' : 'kpi-baja'}>
                {variacion >= 0 ? '▲' : '▼'} {Math.abs(variacion * 100).toFixed(0)} %
              </span> vs. período anterior ({compacto(anterior)})</>
            )}
          </span>
        </div>
        <div className="kpi">
          <span className="kpi-titulo">Capital a rendir</span>
          <span className="kpi-valor">{clp(Number(p.recupero.capital))}</span>
          <span className="kpi-detalle">+ intereses {clp(Number(p.recupero.intereses))}</span>
        </div>
        <div className="kpi">
          <span className="kpi-titulo">Honorarios</span>
          <span className="kpi-valor">{clp(Number(p.recupero.honorarios))}</span>
          <span className="kpi-detalle">ingreso del estudio</span>
        </div>
        <div className="kpi">
          <span className="kpi-titulo">Cartera abierta</span>
          <span className="kpi-valor">{compacto(saldoAbierto)}</span>
          <span className="kpi-detalle">{casosAbiertos} caso(s) en gestión</span>
        </div>
        <div className="kpi">
          <span className="kpi-titulo">Cuotas atrasadas</span>
          <span className="kpi-valor">{p.cuotas_atrasadas}</span>
          <span className="kpi-detalle">{clp(Number(p.monto_atrasado))} por cobrar</span>
        </div>
        <div className="kpi">
          <span className="kpi-titulo">Cumplimiento de cuotas</span>
          <span className="kpi-valor">{cumplimiento === null ? '—' : `${Math.round(cumplimiento * 100)} %`}</span>
          <span className="kpi-detalle">{p.cuotas_pagadas_periodo} de {p.cuotas_vencidas_periodo} que vencieron</span>
        </div>
      </section>

      <section className="tarjeta">
        <h2>Recupero mensual (últimos 12 meses)</h2>
        <GraficoMeses meses={p.meses} />
      </section>

      <div className="panel-grilla">
        <section className="tarjeta">
          <h2>Cartera por estado</h2>
          <div className="tabla-desplazable"><table className="tabla">
            <thead><tr><th>Estado</th><th className="der">Casos</th><th className="der">Saldo</th></tr></thead>
            <tbody>
              {p.cartera.map((e) => (
                <tr key={e.estado}>
                  <td><EtiquetaEstado estado={e.estado} /></td>
                  <td className="der">{e.cantidad}</td>
                  <td className="der"><Plata valor={e.saldo} /></td>
                </tr>
              ))}
            </tbody>
          </table></div>
          <p className="nota">
            {p.gestiones_periodo} gestión(es) en el período.{' '}
            {p.sin_gestion_30_dias > 0 && (
              <><strong>{p.sin_gestion_30_dias}</strong> caso(s) abierto(s) sin gestión hace más de 30 días.{' '}
                <Link to="/cobranzas">Ver cobranzas</Link></>
            )}
          </p>
        </section>

        <section className="tarjeta">
          <h2>Por {etiqueta('cliente', 'cliente').toLowerCase()}</h2>
          <div className="tabla-desplazable"><table className="tabla">
            <thead>
              <tr><th>{etiqueta('cliente', 'Cliente')}</th><th className="der">Abiertas</th>
                <th className="der">Saldo</th><th className="der">Recuperado</th><th>% del asignado</th></tr>
            </thead>
            <tbody>
              {p.por_cliente.map((c) => {
                const pct = Number(c.asignado) > 0 ? Number(c.recuperado_total) / Number(c.asignado) : 0
                return (
                  <tr key={c.cliente_id}>
                    <td>{c.cliente}</td>
                    <td className="der">{c.abiertas}</td>
                    <td className="der"><Plata valor={c.saldo} /></td>
                    <td className="der"><Plata valor={c.recuperado_periodo} /></td>
                    <td>
                      <div className="medidor" title={`Recuperado histórico ${clp(Number(c.recuperado_total))} de ${clp(Number(c.asignado))}`}>
                        <span style={{ width: `${Math.min(100, pct * 100)}%` }} />
                      </div>
                      <small>{(pct * 100).toFixed(1)} %</small>
                    </td>
                  </tr>
                )
              })}
              {p.por_cliente.length === 0 && <tr><td colSpan={5} className="vacio">Sin cartera todavía.</td></tr>}
            </tbody>
          </table></div>
        </section>
      </div>
    </>
  )
}

// Barras apiladas: capital (rinde al mandante) + honorarios (del estudio).
function GraficoMeses({ meses }: { meses: Mes[] }) {
  const [activo, setActivo] = useState<number | null>(null)
  const maximo = useMemo(() => Math.max(1, ...meses.map((m) => Number(m.total))), [meses])
  const ancho = 720
  const alto = 220
  const margenIzq = 56
  const margenAbajo = 26
  const altoUtil = alto - margenAbajo - 10
  const paso = (ancho - margenIzq) / meses.length
  const barra = Math.min(36, paso * 0.6)
  const escala = (v: number) => (v / maximo) * altoUtil
  const marcas = [0, 0.5, 1].map((f) => f * maximo)
  const sinDatos = meses.every((m) => Number(m.total) === 0)

  return (
    <div className="grafico">
      <div className="grafico-leyenda">
        <span><i style={{ background: 'var(--serie-capital)' }} /> Capital</span>
        <span><i style={{ background: 'var(--serie-honorarios)' }} /> Honorarios y otros</span>
      </div>
      {sinDatos ? <p className="suave">Todavía no hay pagos registrados en los últimos 12 meses.</p> : (
        <svg viewBox={`0 0 ${ancho} ${alto}`} role="img" aria-label="Recupero mensual de los últimos 12 meses">
          {marcas.map((v, i) => {
            const y = 10 + altoUtil - escala(v)
            return (
              <g key={i}>
                <line x1={margenIzq} x2={ancho} y1={y} y2={y} className="grafico-grilla" />
                <text x={margenIzq - 6} y={y + 4} textAnchor="end" className="grafico-eje">{compacto(v)}</text>
              </g>
            )
          })}
          {meses.map((m, i) => {
            const x = margenIzq + paso * i + (paso - barra) / 2
            const hCap = escala(Number(m.capital))
            const hHon = escala(Number(m.honorarios) + Number(m.otros))
            const base = 10 + altoUtil
            const fecha = new Date(Number(m.mes.slice(0, 4)), Number(m.mes.slice(5, 7)) - 1, 1)
            return (
              <g key={m.mes} onMouseEnter={() => setActivo(i)} onMouseLeave={() => setActivo(null)}>
                <rect x={margenIzq + paso * i} y={10} width={paso} height={altoUtil} fill="transparent" />
                {hCap > 0 && <rect x={x} y={base - hCap} width={barra} height={hCap} rx={hHon > 2 ? 0 : 4}
                  fill="var(--serie-capital)" opacity={activo === null || activo === i ? 1 : 0.45} />}
                {hHon > 2 && <rect x={x} y={base - hCap - hHon} width={barra} height={hHon - 2} rx={4}
                  fill="var(--serie-honorarios)" opacity={activo === null || activo === i ? 1 : 0.45} />}
                <text x={x + barra / 2} y={alto - 8} textAnchor="middle" className="grafico-eje">
                  {MESES_CORTOS[fecha.getMonth()]}
                </text>
              </g>
            )
          })}
        </svg>
      )}
      {activo !== null && (
        <div className="grafico-tooltip">
          <strong>{MESES_CORTOS[Number(meses[activo].mes.slice(5, 7)) - 1]} {meses[activo].mes.slice(0, 4)}</strong>
          <span>Capital {clp(Number(meses[activo].capital))}</span>
          <span>Honorarios y otros {clp(Number(meses[activo].honorarios) + Number(meses[activo].otros))}</span>
          <span>Total {clp(Number(meses[activo].total))}</span>
        </div>
      )}
      <details>
        <summary className="suave">Ver como tabla</summary>
        <table className="tabla">
          <thead><tr><th>Mes</th><th className="der">Capital</th><th className="der">Honorarios</th><th className="der">Otros</th><th className="der">Total</th></tr></thead>
          <tbody>
            {meses.map((m) => (
              <tr key={m.mes}>
                <td>{MESES_CORTOS[Number(m.mes.slice(5, 7)) - 1]} {m.mes.slice(0, 4)}</td>
                <td className="der"><Plata valor={m.capital} /></td>
                <td className="der"><Plata valor={m.honorarios} /></td>
                <td className="der"><Plata valor={m.otros} /></td>
                <td className="der"><Plata valor={m.total} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  )
}

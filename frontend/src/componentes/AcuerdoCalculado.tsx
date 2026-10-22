import { useEffect, useMemo, useState } from 'react'
import { api, mensajeDeError } from '../api/client'
import type { CobranzaDetalle, PlanAcuerdo } from '../api/tipos'
import { Plata, fechaLegible, fechaLocal, sumarMeses } from './utiles'
import { formatoUF, useUF } from './UF'

// Acuerdo de pago calculado como en la calculadora 3-6-9, dentro de
// "Registrar gestión": saldo capital, UF del día (se trae sola), cuotas,
// interés y pie. El plan se recalcula mientras se escribe y se crea con
// el mismo cálculo del servidor (cada cuota con su desglose).

export interface CuerpoAcuerdo {
  capital: string
  numero_cuotas: number
  tasa_mensual: string
  uf: string | null
  modalidad: 'extrajudicial' | 'judicial'
  abono_inicial: string
  gastos_judiciales: string
  con_comision: boolean
  redondeo: 'arriba' | 'abajo' | null
  fecha_primera_cuota: string
  dia_siguientes: number | null
  fecha_pie: string | null
}

export default function AcuerdoCalculado({ cobranza, alCambiar }: {
  cobranza: CobranzaDetalle
  /** Avisa el cuerpo listo para crear (o null si falta algo). */
  alCambiar: (cuerpo: CuerpoAcuerdo | null) => void
}) {
  const modalidad = cobranza.tipo === 'judicial' ? 'judicial' : 'extrajudicial'
  const { data: ufHoy, isError: sinUF } = useUF()
  const [uf, setUf] = useState('')
  const [capital, setCapital] = useState(String(Math.round(Number(cobranza.monto_actual))))
  const [cuotas, setCuotas] = useState('6')
  const [tasa, setTasa] = useState('0')
  const [pie, setPie] = useState('')
  const [primera, setPrimera] = useState(() => sumarMeses(fechaLocal(), 1))
  const [dia, setDia] = useState('')
  const [redondeo, setRedondeo] = useState<'' | 'arriba' | 'abajo'>('')
  const [gastos, setGastos] = useState('')
  const [comision, setComision] = useState(false)
  const [verTodas, setVerTodas] = useState(false)
  const [plan, setPlan] = useState<PlanAcuerdo | null>(null)
  const [error, setError] = useState('')

  useEffect(() => { if (ufHoy && !uf) setUf(ufHoy.valor) }, [ufHoy, uf])

  const cuerpo = useMemo<CuerpoAcuerdo | null>(() => {
    if (!(Number(capital) > 0) || !(Number(cuotas) >= 1) || !primera) return null
    if (modalidad === 'extrajudicial' && !(Number(uf) > 0)) return null
    return {
      capital, numero_cuotas: Number(cuotas), tasa_mensual: tasa || '0',
      uf: modalidad === 'extrajudicial' ? uf : null, modalidad,
      abono_inicial: pie || '0', gastos_judiciales: modalidad === 'judicial' ? (gastos || '0') : '0',
      con_comision: comision, redondeo: redondeo || null,
      fecha_primera_cuota: primera, dia_siguientes: dia ? Number(dia) : null, fecha_pie: pie ? fechaLocal() : null,
    }
  }, [capital, cuotas, tasa, uf, modalidad, pie, gastos, comision, redondeo, primera, dia])

  // Cálculo en el servidor un momento después de dejar de escribir.
  const clave = JSON.stringify(cuerpo)
  useEffect(() => {
    if (!cuerpo) { setPlan(null); setError(''); alCambiar(null); return }
    const t = window.setTimeout(() => {
      api.post<PlanAcuerdo>('/calculadora/acuerdo', cuerpo)
        .then((r) => { setPlan(r.data); setError(''); alCambiar(cuerpo) })
        .catch((e) => { setPlan(null); setError(mensajeDeError(e)); alCambiar(null) })
    }, 350)
    return () => window.clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clave])

  const filas = plan ? (verTodas ? plan.cuotas : plan.cuotas.slice(0, 4)) : []

  return (
    <div className="acuerdo-calculado">
      <div className="fila">
        <label>Saldo capital *
          <input type="number" min="1" value={capital} onChange={(e) => setCapital(e.target.value)} />
        </label>
        {modalidad === 'extrajudicial' ? (
          <label>UF *
            <input type="number" step="0.01" min="1" value={uf} onChange={(e) => setUf(e.target.value)} />
            <span className="nota">
              {ufHoy ? `UF del ${fechaLegible(ufHoy.fecha)}: ${formatoUF(ufHoy.valor)}`
                : sinUF ? 'No se pudo traer la UF: ingrésala a mano.' : 'Trayendo la UF del día…'}
            </span>
          </label>
        ) : (
          <label>Gastos judiciales
            <input type="number" min="0" value={gastos} onChange={(e) => setGastos(e.target.value)} />
          </label>
        )}
        <label>N° de cuotas *
          <input type="number" min="1" max="120" value={cuotas} onChange={(e) => setCuotas(e.target.value)} />
        </label>
        <label>Interés mensual (%)
          <input type="number" min="0" max="10" step="0.01" value={tasa} onChange={(e) => setTasa(e.target.value)} />
        </label>
      </div>
      <div className="fila">
        <label>Pie hoy
          <input type="number" min="0" value={pie} placeholder="opcional" onChange={(e) => setPie(e.target.value)} />
        </label>
        <div className="chips atajos">
          {[20, 30, 50].map((p) => (
            <button key={p} type="button" className="chip" disabled={!(Number(capital) > 0)}
              onClick={() => setPie(String(Math.round(Number(capital) * p / 100)))}>Pie {p} %</button>
          ))}
        </div>
        <label>Primera cuota *
          <input type="date" value={primera} min={fechaLocal()} onChange={(e) => setPrimera(e.target.value)} />
        </label>
        <label>Día de pago siguientes
          <input type="number" min="1" max="31" value={dia} placeholder="igual" onChange={(e) => setDia(e.target.value)} />
        </label>
        <label>Redondear
          <select value={redondeo} onChange={(e) => setRedondeo(e.target.value as '' | 'arriba' | 'abajo')}>
            <option value="">No</option>
            <option value="arriba">Al mil, arriba</option>
            <option value="abajo">Al mil, abajo</option>
          </select>
        </label>
      </div>
      <label className="check">
        <input type="checkbox" checked={comision} onChange={(e) => setComision(e.target.checked)} />
        Incluir comisión de pago en línea
      </label>

      {error && <div className="alerta-error">{error}</div>}
      {plan && (
        <div className="plan-calculado">
          <div className="plan-cifras">
            <div><span className="suave">Cuota</span><strong><Plata valor={plan.valor_cuota} /></strong>
              <span className="suave">× {plan.numero_cuotas}</span></div>
            {Number(plan.abono_inicial) > 0 && <div><span className="suave">Pie</span><strong><Plata valor={plan.abono_inicial} /></strong></div>}
            <div><span className="suave">Honorarios</span><strong><Plata valor={plan.total_honorarios} /></strong></div>
            <div><span className="suave">Intereses</span><strong><Plata valor={plan.total_intereses} /></strong></div>
            <div><span className="suave">Total a pagar</span><strong><Plata valor={plan.gran_total} /></strong></div>
          </div>
          <table className="tabla tabla-cuotas">
            <thead><tr><th>N°</th><th>Vence</th><th className="der">Capital</th><th className="der">Honorarios</th><th className="der">Interés</th><th className="der">Cuota</th></tr></thead>
            <tbody>
              {filas.map((f) => (
                <tr key={f.numero}>
                  <td className="mono">{f.numero}</td>
                  <td>{f.fecha ? fechaLegible(f.fecha) : '—'}</td>
                  <td className="der"><Plata valor={f.capital} /></td>
                  <td className="der"><Plata valor={f.honorarios} /></td>
                  <td className="der"><Plata valor={f.intereses} /></td>
                  <td className="der negrita"><Plata valor={f.total} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          {plan.cuotas.length > 4 && (
            <button type="button" className="btn-texto" onClick={() => setVerTodas(!verTodas)}>
              {verTodas ? 'Ver menos' : `Ver las ${plan.cuotas.length} cuotas`}
            </button>
          )}
        </div>
      )}
    </div>
  )
}

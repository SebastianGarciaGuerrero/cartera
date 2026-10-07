import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, mensajeDeError } from '../api/client'
import { useAuth } from '../auth'
import type {
  CobranzaDetalle, Modalidad, PlanAcuerdo, ResultadoHonorarios,
} from '../api/tipos'
import { Plata, fechaLegible } from '../componentes/utiles'
import { formatoUF, useUF } from '../componentes/UF'

// Calculadora de cobranza (plan premium): honorarios 3-6-9, desglose de un
// abono y plan de acuerdo de pago / avenimiento. Con ?cobranza=<id> se abre
// con los datos de esa cobranza y el acuerdo se crea directo en ella.
// Todos los cálculos los hace el servidor (una sola fuente de verdad).

type Pestana = 'acuerdo' | 'honorarios' | 'abono'

export default function Calculadora() {
  const { tiene } = useAuth()
  const [params] = useSearchParams()
  const cobranzaId = params.get('cobranza')
  const [pestana, setPestana] = useState<Pestana>('acuerdo')
  const [modalidad, setModalidad] = useState<Modalidad>('extrajudicial')
  const { data: ufHoy, isError: sinUF } = useUF()
  const [uf, setUf] = useState('')

  const { data: cobranza } = useQuery({
    queryKey: ['cobranza', cobranzaId],
    enabled: Boolean(cobranzaId),
    queryFn: async () => (await api.get<CobranzaDetalle>(`/cobranzas/${cobranzaId}`)).data,
  })

  useEffect(() => { if (ufHoy && !uf) setUf(ufHoy.valor) }, [ufHoy, uf])
  useEffect(() => { if (cobranza?.tipo === 'judicial') setModalidad('judicial') }, [cobranza])

  if (!tiene('calculadora_369')) {
    return (
      <>
        <header className="pagina-cabecera"><h1>Calculadora</h1></header>
        <div className="tarjeta">
          La calculadora 3-6-9 y los acuerdos asistidos son parte del plan <strong>Premium</strong>.
          Calcula honorarios por tramos de UF, separa abonos en capital y honorarios, y arma el
          plan de cuotas con interés, pie y comisión de pago en línea, creando el acuerdo directo
          en la cobranza.
        </div>
      </>
    )
  }

  return (
    <>
      <header className="pagina-cabecera">
        <div>
          {cobranza && <Link to={`/cobranzas/${cobranza.id}`} className="volver">← Cobranza N° {cobranza.numero}</Link>}
          <h1>{modalidad === 'judicial' && pestana === 'acuerdo' ? 'Avenimiento' : 'Calculadora'}</h1>
        </div>
      </header>

      <div className="pestanas">
        {([['acuerdo', modalidad === 'judicial' ? 'Avenimiento' : 'Acuerdo de pago'],
           ['honorarios', 'Honorarios'], ['abono', 'Desglose de abono']] as const).map(([clave, nombre]) => (
          <button key={clave} className={`pestana ${pestana === clave ? 'activa' : ''}`}
            onClick={() => setPestana(clave)}>{nombre}</button>
        ))}
      </div>

      <div className="form-finanzas form-alta">
        <div className="fila">
          <label>Modalidad
            <select value={modalidad} onChange={(e) => setModalidad(e.target.value as Modalidad)}>
              <option value="extrajudicial">Extrajudicial (3-6-9)</option>
              <option value="judicial">Judicial (% fijo)</option>
            </select>
          </label>
          {modalidad === 'extrajudicial' && (
            <label>Valor UF
              <input type="number" step="0.01" min="1" value={uf} onChange={(e) => setUf(e.target.value)}
                placeholder="Ej. 39841.72" />
              <span className="suave">
                {ufHoy ? `UF del ${fechaLegible(ufHoy.fecha)}: ${formatoUF(ufHoy.valor)}`
                  : sinUF ? 'No se pudo traer la UF: ingrésala a mano.' : 'Trayendo la UF del día…'}
              </span>
            </label>
          )}
        </div>
      </div>

      {pestana === 'acuerdo' && <Acuerdo modalidad={modalidad} uf={uf} cobranza={cobranza ?? null} />}
      {pestana === 'honorarios' && <Honorarios modalidad={modalidad} uf={uf} />}
      {pestana === 'abono' && <Abono modalidad={modalidad} uf={uf} />}
    </>
  )
}

// Ejecuta el cálculo en el servidor un momento después de dejar de escribir.
function useCalculo<T>(ruta: string, cuerpo: object | null) {
  const [resultado, setResultado] = useState<T | null>(null)
  const [error, setError] = useState('')
  const clave = JSON.stringify(cuerpo)
  useEffect(() => {
    if (!cuerpo) { setResultado(null); setError(''); return }
    const t = setTimeout(() => {
      api.post<T>(ruta, cuerpo)
        .then((r) => { setResultado(r.data); setError('') })
        .catch((err) => { setResultado(null); setError(mensajeDeError(err)) })
    }, 350)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ruta, clave])
  return { resultado, error }
}

const ufValida = (modalidad: Modalidad, uf: string) => modalidad === 'judicial' || Number(uf) > 0

// ------------------------------------------------------------ honorarios

function TablaTramos({ r }: { r: ResultadoHonorarios }) {
  return (
    <table className="tabla">
      <thead><tr><th>Tramo</th><th className="der">Monto base</th><th className="der">%</th><th className="der">Honorarios</th></tr></thead>
      <tbody>
        {r.tramos.map((t, i) => (
          <tr key={i}>
            <td>{r.modalidad === 'judicial' ? 'Capital total'
              : t.hasta_uf ? `${Number(t.desde_uf)} a ${Number(t.hasta_uf)} UF` : `Sobre ${Number(t.desde_uf)} UF`}</td>
            <td className="der"><Plata valor={t.monto_base} /></td>
            <td className="der">{Number(t.porcentaje)} %</td>
            <td className="der"><Plata valor={t.honorarios} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Honorarios({ modalidad, uf }: { modalidad: Modalidad; uf: string }) {
  const [capital, setCapital] = useState('')
  const cuerpo = Number(capital) > 0 && ufValida(modalidad, uf)
    ? { capital, modalidad, uf: modalidad === 'extrajudicial' ? uf : null } : null
  const { resultado: r, error } = useCalculo<ResultadoHonorarios>('/calculadora/honorarios', cuerpo)
  return (
    <section className="tarjeta">
      <label>Capital ($)
        <input type="number" min="1" value={capital} onChange={(e) => setCapital(e.target.value)} autoFocus />
      </label>
      {error && <div className="alerta-error">{error}</div>}
      {r && (
        <>
          {r.capital_uf && <p className="suave">{Number(r.capital_uf).toLocaleString('es-CL')} UF</p>}
          <TablaTramos r={r} />
          <dl className="datos">
            <dt>Total honorarios</dt><dd className="negrita"><Plata valor={r.total_honorarios} /></dd>
            <dt>Total deuda</dt><dd className="negrita"><Plata valor={r.total_deuda} /></dd>
          </dl>
        </>
      )}
    </section>
  )
}

function Abono({ modalidad, uf }: { modalidad: Modalidad; uf: string }) {
  const [abono, setAbono] = useState('')
  const cuerpo = Number(abono) > 0 && ufValida(modalidad, uf)
    ? { abono, modalidad, uf: modalidad === 'extrajudicial' ? uf : null } : null
  const { resultado: r, error } = useCalculo<ResultadoHonorarios>('/calculadora/abono', cuerpo)
  return (
    <section className="tarjeta">
      <p className="nota">Monto total que pagó el deudor: el sistema separa el capital (para el mandante) de los honorarios.</p>
      <label>Abono recibido ($)
        <input type="number" min="1" value={abono} onChange={(e) => setAbono(e.target.value)} autoFocus />
      </label>
      {error && <div className="alerta-error">{error}</div>}
      {r && (
        <>
          <TablaTramos r={r} />
          <dl className="datos">
            <dt>Capital</dt><dd className="negrita"><Plata valor={r.capital} /></dd>
            <dt>Honorarios</dt><dd className="negrita"><Plata valor={r.total_honorarios} /></dd>
          </dl>
        </>
      )}
    </section>
  )
}

// ------------------------------------------------------------ acuerdo

function Acuerdo({ modalidad, uf, cobranza }: {
  modalidad: Modalidad; uf: string; cobranza: CobranzaDetalle | null
}) {
  const navegar = useNavigate()
  const qc = useQueryClient()
  const [capital, setCapital] = useState('')
  const [cuotas, setCuotas] = useState('6')
  const [tasa, setTasa] = useState('0')
  const [pie, setPie] = useState('')
  const [gastos, setGastos] = useState('')
  const [comision, setComision] = useState(false)
  const [redondeo, setRedondeo] = useState<'' | 'arriba' | 'abajo'>('')
  const [primera, setPrimera] = useState('')
  const [diaSiguientes, setDiaSiguientes] = useState('')
  const [fechaPie, setFechaPie] = useState('')
  const [copiado, setCopiado] = useState('')

  useEffect(() => {
    if (cobranza && !capital) setCapital(String(Math.round(Number(cobranza.monto_actual))))
  }, [cobranza, capital])

  const cuerpo = Number(capital) > 0 && Number(cuotas) >= 1 && ufValida(modalidad, uf) ? {
    capital, numero_cuotas: Number(cuotas), tasa_mensual: tasa || '0',
    uf: modalidad === 'extrajudicial' ? uf : null, modalidad,
    abono_inicial: pie || '0', gastos_judiciales: modalidad === 'judicial' ? (gastos || '0') : '0',
    con_comision: comision, redondeo: redondeo || null,
    fecha_primera_cuota: primera || null, dia_siguientes: diaSiguientes ? Number(diaSiguientes) : null,
    fecha_pie: fechaPie || null,
  } : null
  const { resultado: plan, error } = useCalculo<PlanAcuerdo>('/calculadora/acuerdo', cuerpo)

  const crear = useMutation({
    mutationFn: async () => (await api.post('/calculadora/acuerdo/crear', { ...cuerpo, cobranza_id: cobranza!.id })).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['acuerdos', cobranza!.id] })
      qc.invalidateQueries({ queryKey: ['cobranza', cobranza!.id] })
      qc.invalidateQueries({ queryKey: ['gestiones', cobranza!.id] })
      navegar(`/cobranzas/${cobranza!.id}`)
    },
  })

  const conGastos = plan && Number(plan.gastos_judiciales) > 0
  const conComision = plan && Number(plan.comision_total) > 0

  function copiarTabla() {
    if (!plan) return
    const cab = ['N°', 'Fecha', 'Capital', 'Interés', 'Honorarios',
      ...(conGastos ? ['Gastos judiciales'] : []), ...(conComision ? ['Comisión'] : []), 'Total cuota']
    const filas = plan.cuotas.map((f) => [f.numero, f.fecha ? fechaLegible(f.fecha) : '', f.capital, f.intereses,
      f.honorarios, ...(conGastos ? [f.gastos_judiciales] : []), ...(conComision ? [f.comision] : []), f.total])
    if (Number(plan.abono_inicial) > 0) {
      filas.unshift(['PIE', fechaPie ? fechaLegible(fechaPie) : '', plan.capital_pie, '0', plan.honorarios_pie,
        ...(conGastos ? ['0'] : []), ...(conComision ? ['0'] : []), plan.abono_inicial])
    }
    const tsv = [cab, ...filas, ['TOTAL', '', '', '', '', ...(conGastos ? [''] : []), ...(conComision ? [''] : []), plan.gran_total]]
      .map((f) => f.map((v) => typeof v === 'string' && /^-?\d+(\.\d+)?$/.test(v) ? String(Math.round(Number(v))) : String(v)).join('\t'))
      .join('\n')
    navigator.clipboard.writeText(tsv)
    setCopiado('Tabla copiada: pégala en Excel o Word.')
  }

  return (
    <>
      <section className="form-finanzas form-alta">
        <div className="fila">
          <label>Capital ($) *
            <input type="number" min="1" value={capital} onChange={(e) => setCapital(e.target.value)} />
          </label>
          <label>N° de cuotas *
            <input type="number" min="1" max="120" value={cuotas} onChange={(e) => setCuotas(e.target.value)} />
          </label>
          <label>Interés mensual (%)
            <input type="number" min="0" max="10" step="0.01" value={tasa} onChange={(e) => setTasa(e.target.value)} />
          </label>
        </div>
        <div className="fila">
          <label>Pie / abono inicial ($)
            <input type="number" min="0" value={pie} onChange={(e) => setPie(e.target.value)} />
            <button type="button" className="btn btn-chico btn-secundario"
              onClick={() => setPie(String(Math.round(Number(capital) * 0.3)))} disabled={!(Number(capital) > 0)}>
              Pie 30 %
            </button>
          </label>
          <label>Fecha del pie
            <input type="date" value={fechaPie} onChange={(e) => setFechaPie(e.target.value)} />
          </label>
          {modalidad === 'judicial' && (
            <label>Gastos judiciales ($)
              <input type="number" min="0" value={gastos} onChange={(e) => setGastos(e.target.value)} />
            </label>
          )}
        </div>
        <div className="fila">
          <label>Primera cuota vence {cobranza && '*'}
            <input type="date" value={primera} onChange={(e) => setPrimera(e.target.value)} />
          </label>
          <label>Día de pago siguientes
            <input type="number" min="1" max="31" value={diaSiguientes} placeholder="igual a la primera"
              onChange={(e) => setDiaSiguientes(e.target.value)} />
          </label>
          <label>Redondear cuota
            <select value={redondeo} onChange={(e) => setRedondeo(e.target.value as '' | 'arriba' | 'abajo')}>
              <option value="">Sin redondeo</option>
              <option value="arriba">Al mil hacia arriba</option>
              <option value="abajo">Al mil hacia abajo</option>
            </select>
          </label>
          <label className="check">
            <input type="checkbox" checked={comision} onChange={(e) => setComision(e.target.checked)} />
            Incluir comisión de pago en línea
          </label>
        </div>
        {error && <div className="alerta-error">{error}</div>}
      </section>

      {plan && (
        <section className="tarjeta">
          <div className="acuerdo-resumen">
            <div>
              <strong>{plan.numero_cuotas} cuota(s) de <Plata valor={plan.valor_cuota} /></strong>
              {Number(plan.ajuste) !== 0 && <span className="suave"> (ajuste {Number(plan.ajuste) > 0 ? '+' : ''}{Number(plan.ajuste).toLocaleString('es-CL')} en interés)</span>}
            </div>
            <div>Total a pagar: <strong><Plata valor={plan.gran_total} /></strong></div>
          </div>
          <dl className="datos">
            {Number(plan.abono_inicial) > 0 && (<>
              <dt>Pie</dt>
              <dd><Plata valor={plan.abono_inicial} /> <span className="suave">(capital <Plata valor={plan.capital_pie} /> + honorarios <Plata valor={plan.honorarios_pie} />)</span></dd>
            </>)}
            <dt>Capital en cuotas</dt><dd><Plata valor={plan.capital_en_cuotas} /></dd>
            <dt>Total intereses</dt><dd><Plata valor={plan.total_intereses} /></dd>
            <dt>Total honorarios</dt><dd><Plata valor={plan.total_honorarios} /></dd>
            {conComision && (<><dt>Comisión ({Number(plan.comision_pct)} %)</dt><dd><Plata valor={plan.comision_total} /></dd></>)}
          </dl>

          <table className="tabla tabla-cuotas">
            <thead>
              <tr>
                <th>N°</th><th>Vence</th><th className="der">Capital</th><th className="der">Interés</th>
                <th className="der">Honorarios</th>
                {conGastos && <th className="der">Gastos jud.</th>}
                {conComision && <th className="der">Comisión</th>}
                <th className="der">Cuota</th>
              </tr>
            </thead>
            <tbody>
              {plan.cuotas.map((f) => (
                <tr key={f.numero}>
                  <td className="mono">{f.numero}</td>
                  <td>{f.fecha ? fechaLegible(f.fecha) : '—'}</td>
                  <td className="der"><Plata valor={f.capital} /></td>
                  <td className="der"><Plata valor={f.intereses} /></td>
                  <td className="der"><Plata valor={f.honorarios} /></td>
                  {conGastos && <td className="der"><Plata valor={f.gastos_judiciales} /></td>}
                  {conComision && <td className="der"><Plata valor={f.comision} /></td>}
                  <td className="der negrita"><Plata valor={f.total} /></td>
                </tr>
              ))}
            </tbody>
          </table>

          <p className="observaciones">{plan.texto}</p>
          <div className="acciones">
            <button className="btn btn-secundario" onClick={copiarTabla}>Copiar tabla</button>
            <button className="btn btn-secundario" onClick={() => { navigator.clipboard.writeText(plan.texto); setCopiado('Texto copiado.') }}>
              Copiar texto del acuerdo
            </button>
            {cobranza && (
              <button className="btn btn-primario" disabled={!primera || crear.isPending}
                title={primera ? '' : 'Indica la fecha de la primera cuota'}
                onClick={() => crear.mutate()}>
                {crear.isPending ? 'Creando…' : `Crear ${modalidad === 'judicial' ? 'avenimiento' : 'acuerdo'} en la cobranza N° ${cobranza.numero}`}
              </button>
            )}
          </div>
          {copiado && <div className="alerta-exito">{copiado}</div>}
          {crear.isError && <div className="alerta-error">{mensajeDeError(crear.error)}</div>}
        </section>
      )}
    </>
  )
}

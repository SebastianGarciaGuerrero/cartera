import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, mensajeDeError } from '../api/client'
import { useAuth } from '../auth'
import type {
  CobranzaDetalle, Modalidad, PlanAcuerdo, ResultadoHonorarios,
} from '../api/tipos'
import { Plata, fechaLegible } from '../componentes/utiles'
import { formatoUF, useUF } from '../componentes/UF'
import { copiarTablaCuotas } from '../componentes/copiarTabla'
import { useConfirmacion } from '../componentes/ConfirmarGestion'

// Calculadora de cobranza (plan premium): honorarios 3-6-9, desglose de un
// abono y plan de acuerdo de pago / avenimiento. Con ?cobranza=<id> se abre
// con los datos de esa cobranza y el acuerdo se crea directo en ella.
// Todos los cálculos los hace el servidor (una sola fuente de verdad).

type Pestana = 'acuerdo' | 'honorarios' | 'abono'

/** Lo que comparten las tres pestañas: modalidad, UF y % judicial. */
interface Base {
  modalidad: Modalidad
  uf: string
  /** % judicial elegido ('' = el del cliente o el general). */
  pct: string
  cobranzaId: string | null
  alAplicarPct: (pct: string | null | undefined) => void
}

export default function Calculadora() {
  const { tiene } = useAuth()
  const [params] = useSearchParams()
  const cobranzaId = params.get('cobranza')
  const [pestana, setPestana] = useState<Pestana>('acuerdo')
  const [modalidad, setModalidad] = useState<Modalidad>('extrajudicial')
  const { data: ufHoy, isError: sinUF } = useUF()
  const [uf, setUf] = useState('')
  const [pct, setPct] = useState('')
  const [pctAplicado, setPctAplicado] = useState<string | null>(null)

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

  const base: Base = {
    modalidad, uf, pct, cobranzaId: cobranza?.id ?? null,
    alAplicarPct: (p) => setPctAplicado(p != null ? String(Number(p)) : null),
  }
  const judicial = modalidad === 'judicial'

  return (
    <>
      <header className="pagina-cabecera">
        <div>
          {cobranza && <Link to={`/cobranzas/${cobranza.id}`} className="volver">← Cobranza N° {cobranza.numero}</Link>}
          <h1>{judicial && pestana === 'acuerdo' ? 'Avenimiento' : 'Calculadora'}</h1>
          {cobranza && (
            <p className="suave calc-sub">
              {cobranza.deudor?.nombre} · saldo capital <Plata valor={cobranza.monto_actual} />
            </p>
          )}
        </div>
      </header>

      <section className="calc-barra">
        <div className="calc-control">
          <span className="calc-etiqueta">Modalidad</span>
          <div className="segmentos" role="group" aria-label="Modalidad">
            <button type="button" className={!judicial ? 'activo' : ''} onClick={() => setModalidad('extrajudicial')}>
              Extrajudicial · 3-6-9
            </button>
            <button type="button" className={judicial ? 'activo' : ''} onClick={() => setModalidad('judicial')}>
              Judicial · %
            </button>
          </div>
        </div>
        {!judicial ? (
          <label className="calc-control">
            <span className="calc-etiqueta">Valor UF</span>
            <input type="number" step="0.01" min="1" value={uf} onChange={(e) => setUf(e.target.value)} placeholder="39.841,72" />
            <span className="nota">
              {ufHoy ? `UF del ${fechaLegible(ufHoy.fecha)}: ${formatoUF(ufHoy.valor)}`
                : sinUF ? 'No se pudo traer la UF: ingrésala a mano.' : 'Trayendo la UF del día…'}
            </span>
          </label>
        ) : (
          <div className="calc-control">
            <span className="calc-etiqueta">Honorarios judiciales</span>
            <div className="calc-pct">
              <span className="con-sufijo">
                <input type="number" min="0" max="100" step="0.5" value={pct} placeholder={pctAplicado ?? '%'}
                  onChange={(e) => setPct(e.target.value)} aria-label="Porcentaje de honorarios judiciales" />
                <span>%</span>
              </span>
              <div className="chips">
                {[5, 10, 15, 20].map((p) => (
                  <button key={p} type="button" className={`chip ${Number(pct || pctAplicado) === p ? 'elegido' : ''}`}
                    onClick={() => setPct(String(p))}>{p} %</button>
                ))}
              </div>
            </div>
            <span className="nota">
              {pct ? 'Elegido para este cálculo.' : cobranza ? 'El del cliente de la cobranza (o el general del estudio).' : 'El general del estudio.'}
            </span>
          </div>
        )}
      </section>

      <div className="calc-pestanas" role="tablist">
        {([['acuerdo', judicial ? 'Avenimiento' : 'Acuerdo de pago', 'Plan de cuotas con pie e interés'],
           ['honorarios', 'Honorarios', 'De un capital'],
           ['abono', 'Desglose de abono', 'Lo pagado en capital y honorarios']] as const).map(([clave, nombre, ayuda]) => (
          <button key={clave} role="tab" aria-selected={pestana === clave}
            className={`calc-pestana ${pestana === clave ? 'activa' : ''}`} onClick={() => setPestana(clave)}>
            <strong>{nombre}</strong>
            <span>{ayuda}</span>
          </button>
        ))}
      </div>

      {pestana === 'acuerdo' && <Acuerdo base={base} cobranza={cobranza ?? null} />}
      {pestana === 'honorarios' && <Honorarios base={base} />}
      {pestana === 'abono' && <Abono base={base} />}
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

const ufValida = (b: Base) => b.modalidad === 'judicial' || Number(b.uf) > 0
const comun = (b: Base) => ({
  modalidad: b.modalidad, uf: b.modalidad === 'extrajudicial' ? b.uf : null,
  pct_judicial: b.modalidad === 'judicial' && b.pct !== '' ? b.pct : null, cobranza_id: b.cobranzaId,
})

/** 9.5 → "9,5 %" */
const pctTexto = (v: number) => `${(Math.round(v * 100) / 100).toLocaleString('es-CL')} %`

function Cifra({ etiqueta, children, fuerte }: { etiqueta: string; children: ReactNode; fuerte?: boolean }) {
  return (
    <div className={`calc-cifra ${fuerte ? 'fuerte' : ''}`}>
      <span>{etiqueta}</span>
      <strong>{children}</strong>
    </div>
  )
}

// ------------------------------------------------------------ honorarios

function TablaTramos({ r }: { r: ResultadoHonorarios }) {
  return (
    <table className="tabla calc-tramos">
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

function Honorarios({ base }: { base: Base }) {
  const [capital, setCapital] = useState('')
  const cuerpo = Number(capital) > 0 && ufValida(base) ? { capital, ...comun(base) } : null
  const { resultado: r, error } = useCalculo<ResultadoHonorarios>('/calculadora/honorarios', cuerpo)
  useEffect(() => { if (r) base.alAplicarPct(r.pct_judicial) }, [r]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <section className="tarjeta calc-simple">
      <label className="calc-entrada">
        Capital adeudado
        <input type="number" min="1" value={capital} onChange={(e) => setCapital(e.target.value)} autoFocus placeholder="$" />
      </label>
      {error && <div className="alerta-error">{error}</div>}
      {r ? (
        <>
          <div className="calc-cifras">
            <Cifra etiqueta="Honorarios" fuerte><Plata valor={r.total_honorarios} /></Cifra>
            <Cifra etiqueta="Total a cobrar"><Plata valor={r.total_deuda} /></Cifra>
            <Cifra etiqueta="Equivale a">{pctTexto(Number(r.total_honorarios) / Number(r.capital) * 100)}</Cifra>
            {r.capital_uf && <Cifra etiqueta="Capital en UF">{Number(r.capital_uf).toLocaleString('es-CL')}</Cifra>}
          </div>
          <TablaTramos r={r} />
        </>
      ) : !error && <p className="suave calc-vacio">Escribe el capital para ver los honorarios por tramo.</p>}
    </section>
  )
}

function Abono({ base }: { base: Base }) {
  const [abono, setAbono] = useState('')
  const cuerpo = Number(abono) > 0 && ufValida(base) ? { abono, ...comun(base) } : null
  const { resultado: r, error } = useCalculo<ResultadoHonorarios>('/calculadora/abono', cuerpo)
  useEffect(() => { if (r) base.alAplicarPct(r.pct_judicial) }, [r]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <section className="tarjeta calc-simple">
      <label className="calc-entrada">
        Monto que pagó el deudor
        <input type="number" min="1" value={abono} onChange={(e) => setAbono(e.target.value)} autoFocus placeholder="$" />
      </label>
      {error && <div className="alerta-error">{error}</div>}
      {r ? (
        <>
          <div className="calc-cifras">
            <Cifra etiqueta="Capital (descuenta la deuda)" fuerte><Plata valor={r.capital} /></Cifra>
            <Cifra etiqueta="Honorarios"><Plata valor={r.total_honorarios} /></Cifra>
            <Cifra etiqueta="Equivale a">{pctTexto(Number(r.total_honorarios) / Number(r.capital) * 100)} del capital</Cifra>
          </div>
          <TablaTramos r={r} />
        </>
      ) : !error && <p className="suave calc-vacio">Escribe lo que pagó: se separa en capital (para el cliente) y honorarios.</p>}
    </section>
  )
}

// ------------------------------------------------------------ acuerdo

function Acuerdo({ base, cobranza }: { base: Base; cobranza: CobranzaDetalle | null }) {
  const navegar = useNavigate()
  const qc = useQueryClient()
  const { etiqueta } = useAuth()
  const { pedir, modal } = useConfirmacion()
  const judicial = base.modalidad === 'judicial'
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

  const cuerpo = Number(capital) > 0 && Number(cuotas) >= 1 && ufValida(base) ? {
    capital, numero_cuotas: Number(cuotas), tasa_mensual: tasa || '0', ...comun(base),
    abono_inicial: pie || '0', gastos_judiciales: judicial ? (gastos || '0') : '0',
    con_comision: comision, redondeo: redondeo || null,
    fecha_primera_cuota: primera || null, dia_siguientes: diaSiguientes ? Number(diaSiguientes) : null,
    fecha_pie: fechaPie || null,
  } : null
  const { resultado: plan, error } = useCalculo<PlanAcuerdo>('/calculadora/acuerdo', cuerpo)
  useEffect(() => { if (plan) base.alAplicarPct(plan.pct_judicial) }, [plan]) // eslint-disable-line react-hooks/exhaustive-deps

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
  const nombre = judicial ? 'avenimiento' : 'acuerdo'

  function copiarTabla() {
    if (!plan) return
    copiarTablaCuotas(plan, { fechaPie: fechaPie || null, cliente: etiqueta('cliente', 'cliente') })
      .then(() => setCopiado('Tabla copiada: pégala en Word, Excel o el correo.'))
      .catch(() => setCopiado('No se pudo copiar la tabla. Revisa los permisos del navegador.'))
  }

  return (
    <div className="calc-grilla">
      <section className="tarjeta calc-datos">
        <div className="calc-grupo">
          <h3>Deuda</h3>
          <div className="fila">
            <label>Capital *
              <input type="number" min="1" value={capital} onChange={(e) => setCapital(e.target.value)} placeholder="$" />
            </label>
            {judicial && (
              <label>Gastos judiciales
                <input type="number" min="0" value={gastos} onChange={(e) => setGastos(e.target.value)} placeholder="$" />
              </label>
            )}
          </div>
        </div>

        <div className="calc-grupo">
          <h3>Pie</h3>
          <div className="fila">
            <label>Monto del pie
              <input type="number" min="0" value={pie} onChange={(e) => setPie(e.target.value)} placeholder="opcional" />
            </label>
            <label>Fecha del pie
              <input type="date" value={fechaPie} onChange={(e) => setFechaPie(e.target.value)} />
            </label>
          </div>
          <div className="chips">
            {[20, 30, 50].map((p) => (
              <button key={p} type="button" className="chip" disabled={!(Number(capital) > 0)}
                onClick={() => setPie(String(Math.round(Number(capital) * p / 100)))}>Pie {p} %</button>
            ))}
            {pie && <button type="button" className="chip" onClick={() => setPie('')}>Sin pie</button>}
          </div>
        </div>

        <div className="calc-grupo">
          <h3>Cuotas</h3>
          <div className="fila">
            <label>N° de cuotas *
              <input type="number" min="1" max="120" value={cuotas} onChange={(e) => setCuotas(e.target.value)} />
            </label>
            <label>Interés mensual
              <span className="con-sufijo">
                <input type="number" min="0" max="10" step="0.01" value={tasa} onChange={(e) => setTasa(e.target.value)} />
                <span>%</span>
              </span>
            </label>
          </div>
          <div className="chips">
            {[3, 6, 9, 12].map((n) => (
              <button key={n} type="button" className={`chip ${Number(cuotas) === n ? 'elegido' : ''}`}
                onClick={() => setCuotas(String(n))}>{n} cuotas</button>
            ))}
          </div>
          <div className="fila">
            <label>Primera cuota vence {cobranza && '*'}
              <input type="date" value={primera} onChange={(e) => setPrimera(e.target.value)} />
            </label>
            <label>Día de pago siguientes
              <input type="number" min="1" max="31" value={diaSiguientes} placeholder="igual a la primera"
                onChange={(e) => setDiaSiguientes(e.target.value)} />
            </label>
          </div>
          <div className="fila">
            <label>Redondear cuota
              <select value={redondeo} onChange={(e) => setRedondeo(e.target.value as '' | 'arriba' | 'abajo')}>
                <option value="">Sin redondeo</option>
                <option value="arriba">Al mil hacia arriba</option>
                <option value="abajo">Al mil hacia abajo</option>
              </select>
            </label>
            <label className="check">
              <input type="checkbox" checked={comision} onChange={(e) => setComision(e.target.checked)} />
              Comisión de pago en línea
            </label>
          </div>
        </div>
        {error && <div className="alerta-error">{error}</div>}
      </section>

      <aside className="tarjeta calc-resultado" aria-live="polite">
        {plan ? (
          <>
            <span className="calc-etiqueta">{plan.numero_cuotas} cuota{plan.numero_cuotas === 1 ? '' : 's'} de</span>
            <div className="calc-grande"><Plata valor={plan.valor_cuota} /></div>
            {Number(plan.ajuste) !== 0 && (
              <span className="nota">Ajuste {Number(plan.ajuste) > 0 ? '+' : ''}{Number(plan.ajuste).toLocaleString('es-CL')} en el interés para cuadrar</span>
            )}
            <dl className="calc-desglose">
              {Number(plan.abono_inicial) > 0 && (<>
                <dt>Pie{fechaPie ? ` (${fechaLegible(fechaPie)})` : ''}</dt><dd><Plata valor={plan.abono_inicial} /></dd>
              </>)}
              <dt>Capital en cuotas</dt><dd><Plata valor={plan.capital_en_cuotas} /></dd>
              <dt>Intereses</dt><dd><Plata valor={plan.total_intereses} /></dd>
              <dt>Honorarios{judicial && plan.pct_judicial ? ` (${Number(plan.pct_judicial)} %)` : ''}</dt>
              <dd><Plata valor={plan.total_honorarios} /></dd>
              {conGastos && (<><dt>Gastos judiciales</dt><dd><Plata valor={plan.gastos_judiciales} /></dd></>)}
              {conComision && (<><dt>Comisión ({Number(plan.comision_pct)} %)</dt><dd><Plata valor={plan.comision_total} /></dd></>)}
              <dt className="calc-total">Total a pagar</dt><dd className="calc-total"><Plata valor={plan.gran_total} /></dd>
            </dl>
            <div className="calc-acciones">
              {cobranza && (
                <button className="btn btn-primario" disabled={!primera || crear.isPending}
                  title={primera ? '' : 'Indica la fecha de la primera cuota'}
                  onClick={() => pedir({
                    titulo: `Crear ${nombre} en la cobranza N° ${cobranza.numero}`,
                    gestion: `${judicial ? 'AVENIMIENTO' : 'ACUERDO DE PAGO'}: ${plan.texto}`,
                    detalle: <p className="suave">El pie y cada cuota quedarán en tu agenda y en los avisos.</p>,
                    confirmar: 'Sí, crear', accion: () => crear.mutateAsync(),
                  })}>
                  {crear.isPending ? 'Creando…' : `Crear ${nombre} en la cobranza`}
                </button>
              )}
              <button className="btn btn-secundario" onClick={copiarTabla}>Copiar tabla</button>
              <button className="btn btn-secundario" onClick={() => { navigator.clipboard.writeText(plan.texto); setCopiado('Texto copiado.') }}>
                Copiar texto
              </button>
            </div>
            {cobranza && !primera && <p className="nota">Para crearlo, indica cuándo vence la primera cuota.</p>}
            {copiado && <div className="alerta-exito">{copiado}</div>}
            {crear.isError && <div className="alerta-error">{mensajeDeError(crear.error)}</div>}
          </>
        ) : (
          <p className="suave calc-vacio">
            {ufValida(base) ? 'Completa el capital y las cuotas para ver el plan.' : 'Falta el valor de la UF.'}
          </p>
        )}
      </aside>

      {plan && (
        <section className="tarjeta calc-plan">
          <h3>Plan de cuotas</h3>
          <div className="tabla-desplazable">
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
                {Number(plan.abono_inicial) > 0 && (
                  <tr className="fila-pie">
                    <td className="negrita">Pie</td>
                    <td>{fechaPie ? fechaLegible(fechaPie) : '—'}</td>
                    <td className="der"><Plata valor={plan.capital_pie} /></td>
                    <td className="der"><Plata valor={0} /></td>
                    <td className="der"><Plata valor={plan.honorarios_pie} /></td>
                    {conGastos && <td className="der"><Plata valor={0} /></td>}
                    {conComision && <td className="der"><Plata valor={0} /></td>}
                    <td className="der negrita"><Plata valor={plan.abono_inicial} /></td>
                  </tr>
                )}
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
          </div>
          <h3 className="separado">Texto del {nombre}</h3>
          <blockquote className="calc-texto">{plan.texto}</blockquote>
        </section>
      )}
      {modal}
    </div>
  )
}

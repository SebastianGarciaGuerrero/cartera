import { useState } from 'react'
import type { FormEvent } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, mensajeDeError } from '../api/client'
import type {
  Cobranza, Acuerdo, AcuerdoDetalle, Cuota, Pago, EstadoCuota,
} from '../api/tipos'
import { Plata, fechaLegible } from './utiles'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth'
import { useUF } from './UF'
import type { Modalidad, ResultadoHonorarios } from '../api/tipos'

// Sección financiera de la ficha de cobranza: acuerdo de pago con sus
// cuotas, historial de pagos, y registro de pagos (por cuota o directos).
// El backend aplica la cascada: saldo, estado de cuota, acuerdo y cobranza.

const FORMAS_PAGO = [
  'transferencia', 'cheque', 'efectivo', 'deposito',
  'flow', 'presencial', 'bonificacion', 'otro',
] as const

const NOMBRE_CUOTA: Record<EstadoCuota, string> = {
  pendiente: 'Pendiente',
  pagada: 'Pagada',
  vencida: 'Vencida',
  pagada_parcial: 'Pago parcial',
}

// Reutiliza los colores de las etiquetas de cobranza.
const CLASE_CUOTA: Record<EstadoCuota, string> = {
  pendiente: 'etiqueta-archivada',
  pagada: 'etiqueta-pagada',
  vencida: 'etiqueta-castigo',
  pagada_parcial: 'etiqueta-acuerdo_pago',
}

export default function Finanzas({ cobranza }: { cobranza: Cobranza }) {
  const qc = useQueryClient()
  const cobranzaId = cobranza.id

  const { data: acuerdos } = useQuery({
    queryKey: ['acuerdos', cobranzaId],
    queryFn: async () =>
      (await api.get<Acuerdo[]>('/acuerdos/', { params: { cobranza_id: cobranzaId } })).data,
  })

  // El acuerdo relevante: el vigente si existe, si no el más reciente.
  const acuerdo = acuerdos?.find((a) => a.estado === 'vigente') ?? acuerdos?.[0]

  const { data: acuerdoDetalle } = useQuery({
    queryKey: ['acuerdo', acuerdo?.id],
    enabled: acuerdo !== undefined,
    queryFn: async () =>
      (await api.get<AcuerdoDetalle>(`/acuerdos/${acuerdo!.id}`)).data,
  })

  const { data: pagos } = useQuery({
    queryKey: ['pagos', cobranzaId],
    queryFn: async () =>
      (await api.get<Pago[]>('/pagos/', { params: { cobranza_id: cobranzaId } })).data,
  })

  // Refresca todo lo que la cascada del backend puede haber cambiado.
  function refrescarTodo() {
    qc.invalidateQueries({ queryKey: ['cobranza', cobranzaId] })
    qc.invalidateQueries({ queryKey: ['cobranzas'] })
    qc.invalidateQueries({ queryKey: ['acuerdos', cobranzaId] })
    qc.invalidateQueries({ queryKey: ['acuerdo'] })
    qc.invalidateQueries({ queryKey: ['pagos', cobranzaId] })
  }

  // --- Estado del formulario de pago (por cuota o directo) ---
  const [pagando, setPagando] = useState<Cuota | 'directo' | null>(null)

  return (
    <section className="tarjeta finanzas">
      <h2>Acuerdo de pago y pagos</h2>

      {acuerdoDetalle ? (
        <>
          <div className="acuerdo-resumen">
            <div>
              <span className="suave">Acuerdo del {fechaLegible(acuerdoDetalle.fecha_acuerdo)}</span>{' '}
              <span className={`etiqueta ${acuerdoDetalle.estado === 'vigente'
                ? 'etiqueta-activa'
                : acuerdoDetalle.estado === 'cumplido'
                  ? 'etiqueta-pagada'
                  : 'etiqueta-castigo'}`}>
                {acuerdoDetalle.estado}
              </span>
            </div>
            <div>
              <Plata valor={acuerdoDetalle.monto_total_acordado} /> en{' '}
              {acuerdoDetalle.numero_cuotas} cuota(s)
              {Number(acuerdoDetalle.pie) > 0 && (
                <span className="suave"> · pie <Plata valor={acuerdoDetalle.pie} /></span>
              )}
            </div>
          </div>

          <table className="tabla tabla-cuotas">
            <thead>
              <tr>
                <th>Cuota</th><th>Vence</th>
                <th className="der">Monto</th><th className="der">Pagado</th>
                <th>Estado</th><th></th>
              </tr>
            </thead>
            <tbody>
              {acuerdoDetalle.cuotas.map((c) => (
                <tr key={c.id}>
                  <td className="mono">{c.numero_cuota}/{acuerdoDetalle.numero_cuotas}</td>
                  <td>{fechaLegible(c.fecha_vencimiento)}</td>
                  <td className="der"><Plata valor={c.monto} /></td>
                  <td className="der"><Plata valor={c.monto_pagado} /></td>
                  <td>
                    <span className={`etiqueta ${CLASE_CUOTA[c.estado]}`}>
                      {NOMBRE_CUOTA[c.estado]}
                    </span>
                  </td>
                  <td>
                    {c.estado !== 'pagada' && acuerdoDetalle.estado === 'vigente' && (
                      <button
                        className="btn btn-chico btn-secundario"
                        onClick={() => setPagando(c)}
                      >
                        Registrar pago
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      ) : (
        <>
          <LinkCalculadora cobranzaId={cobranzaId} />
          <FormNuevoAcuerdo cobranza={cobranza} alCrear={refrescarTodo} />
        </>
      )}

      {pagando && (
        <FormPago
          cobranzaId={cobranzaId}
          modalidad={cobranza.tipo}
          cuota={pagando === 'directo' ? null : pagando}
          alTerminar={() => { setPagando(null); refrescarTodo() }}
          alCancelar={() => setPagando(null)}
        />
      )}

      <div className="finanzas-pie">
        <h2>Pagos recibidos ({pagos?.length ?? 0})</h2>
        {!pagando && (
          <button className="btn btn-chico btn-secundario" onClick={() => setPagando('directo')}>
            + Registrar abono
          </button>
        )}
      </div>

      {pagos && pagos.length > 0 ? (
        <table className="tabla">
          <thead>
            <tr>
              <th>Fecha</th><th className="der">Total</th>
              <th className="der">Capital</th><th className="der">Honorarios</th>
              <th>Tipo</th><th>Forma</th><th>Comprobante</th>
            </tr>
          </thead>
          <tbody>
            {pagos.map((p) => (
              <tr key={p.id}>
                <td>{fechaLegible(p.fecha_pago)}</td>
                <td className="der"><Plata valor={p.monto} /></td>
                <td className="der"><Plata valor={p.capital} /></td>
                <td className="der"><Plata valor={p.honorarios} /></td>
                <td>{p.estado_pago}</td>
                <td>{p.forma_pago ?? '—'}</td>
                <td className="mono">{p.numero_comprobante ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="suave">Aún no hay pagos registrados.</p>
      )}
    </section>
  )
}

// ------------------------------------------------------------
// Formulario para crear un acuerdo (solo si no hay uno vigente)
// ------------------------------------------------------------

function FormNuevoAcuerdo({ cobranza, alCrear }: { cobranza: Cobranza; alCrear: () => void }) {
  const [abierto, setAbierto] = useState(false)
  const [monto, setMonto] = useState(cobranza.monto_actual)
  const [pie, setPie] = useState('0')
  const [cuotas, setCuotas] = useState('6')
  const [primeraCuota, setPrimeraCuota] = useState('')
  const [diaPago, setDiaPago] = useState('5')
  const [error, setError] = useState('')

  const crear = useMutation({
    mutationFn: async () => {
      await api.post('/acuerdos/', {
        cobranza_id: cobranza.id,
        monto_total_acordado: monto,
        pie,
        numero_cuotas: Number(cuotas),
        fecha_primera_cuota: primeraCuota,
        dia_pago: Number(diaPago) || null,
      })
    },
    onSuccess: () => { setAbierto(false); alCrear() },
    onError: (err) => setError(mensajeDeError(err)),
  })

  if (!abierto) {
    return (
      <div>
        <p className="suave">Esta cobranza no tiene un acuerdo de pago vigente.</p>
        <button className="btn btn-secundario" onClick={() => setAbierto(true)}>
          + Crear acuerdo de pago
        </button>
      </div>
    )
  }

  function alEnviar(e: FormEvent) {
    e.preventDefault()
    setError('')
    crear.mutate()
  }

  return (
    <form className="form-finanzas" onSubmit={alEnviar}>
      <div className="fila">
        <label>
          Monto total acordado
          <input type="number" min="1" value={monto} onChange={(e) => setMonto(e.target.value)} required />
        </label>
        <label>
          Pie
          <input type="number" min="0" value={pie} onChange={(e) => setPie(e.target.value)} />
        </label>
        <label>
          N° de cuotas
          <input type="number" min="1" max="120" value={cuotas} onChange={(e) => setCuotas(e.target.value)} required />
        </label>
      </div>
      <div className="fila">
        <label>
          Primera cuota vence
          <input type="date" value={primeraCuota} onChange={(e) => setPrimeraCuota(e.target.value)} required />
        </label>
        <label>
          Día de pago (1-31)
          <input type="number" min="1" max="31" value={diaPago} onChange={(e) => setDiaPago(e.target.value)} />
        </label>
      </div>
      <p className="nota">
        Las cuotas se generan automáticamente en partes iguales y la cobranza
        pasa a estado "acuerdo de pago".
      </p>
      {error && <div className="alerta-error">{error}</div>}
      <div className="fila">
        <button className="btn btn-primario" disabled={crear.isPending}>
          {crear.isPending ? 'Creando…' : 'Crear acuerdo'}
        </button>
        <button type="button" className="btn btn-secundario" onClick={() => setAbierto(false)}>
          Cancelar
        </button>
      </div>
    </form>
  )
}

// ------------------------------------------------------------
// Formulario para registrar un pago (de una cuota o directo)
// ------------------------------------------------------------

function LinkCalculadora({ cobranzaId }: { cobranzaId: string }) {
  const { tiene } = useAuth()
  if (!tiene('calculadora_369')) return null
  return (
    <p className="nota">
      <Link to={`/calculadora?cobranza=${cobranzaId}`}>Armar el acuerdo con la calculadora 3-6-9</Link>
      {' '}(interés, pie, honorarios por tramos y texto del acuerdo).
    </p>
  )
}

// Para una cuota calculada con la calculadora, su desglose ya está guardado.
const entero = (v: string | null | undefined) => (v == null ? '' : String(Math.round(Number(v))))

export function FormPago({ cobranzaId, cuota, modalidad = 'extrajudicial', alTerminar, alCancelar }: {
  cobranzaId: string
  cuota: Cuota | null
  modalidad?: Modalidad
  alTerminar: () => void
  alCancelar: () => void
}) {
  // Desglose del abono. El CAPITAL es la guía: es lo único que descuenta
  // el saldo. Honorarios varían según el abono y la UF del día.
  const conDesglose = cuota != null && cuota.capital != null && Number(cuota.monto_pagado) === 0
  const [capital, setCapital] = useState(conDesglose ? entero(cuota!.capital) : '')
  const [honorarios, setHonorarios] = useState(conDesglose ? entero(cuota!.honorarios) : '')
  const [interes, setInteres] = useState(conDesglose ? entero(cuota!.intereses) : '')
  const [gastos, setGastos] = useState(conDesglose
    ? String(Math.round(Number(cuota!.gastos_judiciales ?? 0) + Number(cuota!.comision ?? 0))) : '')
  const [forma, setForma] = useState('transferencia')
  const [comprobante, setComprobante] = useState('')
  const [error, setError] = useState('')

  const total =
    (Number(capital) || 0) + (Number(honorarios) || 0) +
    (Number(interes) || 0) + (Number(gastos) || 0)

  const pagar = useMutation({
    mutationFn: async () => {
      await api.post('/pagos/', {
        cobranza_id: cobranzaId,
        cuota_id: cuota?.id ?? null,
        monto: String(total),
        capital: capital || '0',
        honorarios: honorarios || '0',
        intereses: interes || '0',
        gastos_judiciales: gastos || '0',
        forma_pago: forma,
        numero_comprobante: comprobante || null,
        estado_pago: cuota ? 'cuota' : 'abono',
      })
    },
    onSuccess: alTerminar,
    onError: (err) => setError(mensajeDeError(err)),
  })

  function alEnviar(e: FormEvent) {
    e.preventDefault()
    setError('')
    pagar.mutate()
  }

  return (
    <form className="form-finanzas form-pago" onSubmit={alEnviar}>
      <h3>
        {cuota
          ? `Registrar pago de la cuota ${cuota.numero_cuota}`
          : 'Registrar abono'}
      </h3>
      {conDesglose && (
        <p className="nota">Desglose de la cuota según el acuerdo calculado. Ajústalo si el pago fue distinto.</p>
      )}
      {!conDesglose && (
        <DesgloseAutomatico modalidad={modalidad} alCalcular={(c, h) => {
          setCapital(c); setHonorarios(h); setInteres(''); setGastos('')
        }} />
      )}
      <div className="fila">
        <label>
          Capital *
          <input type="number" min="1" value={capital}
            onChange={(e) => setCapital(e.target.value)} required autoFocus />
        </label>
        <label>
          Honorarios *
          <input type="number" min="0" value={honorarios}
            onChange={(e) => setHonorarios(e.target.value)} required />
        </label>
        <label>
          Interés
          <input type="number" min="0" value={interes}
            onChange={(e) => setInteres(e.target.value)} placeholder="opcional" />
        </label>
        <label>
          Gastos judiciales
          <input type="number" min="0" value={gastos}
            onChange={(e) => setGastos(e.target.value)} placeholder="opcional" />
        </label>
      </div>
      <div className="fila">
        <label>
          Forma de pago
          <select value={forma} onChange={(e) => setForma(e.target.value)}>
            {FORMAS_PAGO.map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
        </label>
        <label>
          N° comprobante
          <input value={comprobante} onChange={(e) => setComprobante(e.target.value)} placeholder="opcional" />
        </label>
        <div className="total-abono">
          Total: <Plata valor={total} />
        </div>
      </div>
      <p className="nota">
        Solo el CAPITAL descuenta el saldo de la cobranza. El pago queda en el
        recupero del mes automáticamente y deja una gestión en el historial.
      </p>
      {error && <div className="alerta-error">{error}</div>}
      <div className="fila">
        <button className="btn btn-primario" disabled={pagar.isPending || total <= 0}>
          {pagar.isPending ? 'Registrando…' : `Registrar ${cuota ? 'pago' : 'abono'}`}
        </button>
        <button type="button" className="btn btn-secundario" onClick={alCancelar}>
          Cancelar
        </button>
      </div>
    </form>
  )
}

// Pagó un total: la calculadora 3-6-9 lo separa en capital y honorarios.
function DesgloseAutomatico({ modalidad, alCalcular }: {
  modalidad: Modalidad
  alCalcular: (capital: string, honorarios: string) => void
}) {
  const { tiene } = useAuth()
  const { data: uf } = useUF()
  const [total, setTotal] = useState('')
  const [error, setError] = useState('')
  const calcular = useMutation({
    mutationFn: async () => (await api.post<ResultadoHonorarios>('/calculadora/abono', {
      abono: total, modalidad, uf: modalidad === 'extrajudicial' ? uf?.valor ?? null : null,
    })).data,
    onSuccess: (r) => { setError(''); alCalcular(entero(r.capital), entero(r.total_honorarios)) },
    onError: (err) => setError(mensajeDeError(err)),
  })
  if (!tiene('calculadora_369')) return null
  return (
    <div className="fila">
      <label>
        Total recibido (para separar con 3-6-9{modalidad === 'judicial' ? ' judicial' : ''})
        <input type="number" min="1" value={total} onChange={(e) => setTotal(e.target.value)} />
      </label>
      <button type="button" className="btn btn-secundario" disabled={!(Number(total) > 0) || calcular.isPending}
        onClick={() => calcular.mutate()}>
        Separar capital y honorarios
      </button>
      {error && <div className="alerta-error">{error}</div>}
    </div>
  )
}

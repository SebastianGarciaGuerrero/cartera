import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, mensajeDeError, descargarArchivo } from '../api/client'
import { refrescarCaso } from '../api/refrescar'
import type {
  Cobranza, Acuerdo, AcuerdoDetalle, Cuota, Pago, EstadoCuota,
} from '../api/tipos'
import { Plata, fechaLegible, fechaLocal } from './utiles'
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

export const NOMBRE_CUOTA: Record<EstadoCuota, string> = {
  pendiente: 'Pendiente',
  pagada: 'Pagada',
  vencida: 'Vencida',
  pagada_parcial: 'Pago parcial',
}

// Reutiliza los colores de las etiquetas de cobranza.
export const CLASE_CUOTA: Record<EstadoCuota, string> = {
  pendiente: 'etiqueta-archivada',
  pagada: 'etiqueta-pagada',
  vencida: 'etiqueta-castigo',
  pagada_parcial: 'etiqueta-acuerdo_pago',
}

export default function Finanzas({ cobranza, alPedirAcuerdo }: {
  cobranza: Cobranza
  /** Abre "Registrar gestión" en modo acuerdo (gestión + acuerdo en un paso). */
  alPedirAcuerdo?: () => void
}) {
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
  const refrescarTodo = () => refrescarCaso(qc, cobranzaId)

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
            <button className="btn btn-chico btn-secundario"
              onClick={() => descargarArchivo(`/documentos/acuerdo/${acuerdoDetalle.id}`)}>
              {cobranza.tipo === 'judicial' ? 'Avenimiento' : 'Acuerdo'} (Word)
            </button>
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
        <div className="sin-acuerdo">
          <p className="suave">Esta cobranza no tiene un acuerdo de pago vigente.</p>
          {alPedirAcuerdo && (
            <button className="btn btn-secundario" onClick={alPedirAcuerdo}>+ Registrar acuerdo de pago</button>
          )}
          <LinkCalculadora cobranzaId={cobranzaId} />
        </div>
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


// ------------------------------------------------------------
// Formulario de pago (de una cuota o abono libre)
// ------------------------------------------------------------
// Se ingresa lo que pagó el deudor; el desglose se arma solo:
//  - cuota de un acuerdo calculado: el desglose guardado de la cuota;
//  - plan con calculadora: capital y honorarios 3-6-9 con la UF del día
//    del pago;
//  - si no: todo a capital.
// Siempre se puede editar el desglose a mano.

const entero = (v: string | null | undefined) => (v == null ? '' : String(Math.round(Number(v))))

export interface PagoRegistrado {
  monto: number
  capital: number
  honorarios: number
  intereses: number
  gastos: number
  fecha: string
  cuota: number | null
}

export function FormPago({ cobranzaId, cuota, modalidad = 'extrajudicial', alTerminar, alCancelar }: {
  cobranzaId: string
  cuota: Cuota | null
  modalidad?: Modalidad
  alTerminar: (pago: PagoRegistrado) => void
  alCancelar: () => void
}) {
  const { tiene } = useAuth()
  const conCalculadora = tiene('calculadora_369')
  const saldoCuota = cuota ? Math.max(0, Number(cuota.monto) - Number(cuota.monto_pagado)) : 0
  const desgloseGuardado = cuota != null && cuota.capital != null && Number(cuota.monto_pagado) === 0

  const [total, setTotal] = useState(cuota ? String(Math.round(saldoCuota)) : '')
  const [fecha, setFecha] = useState(fechaLocal())
  const [forma, setForma] = useState('transferencia')
  const [comprobante, setComprobante] = useState('')
  const [comentario, setComentario] = useState('')
  const [editando, setEditando] = useState(false)
  const [capital, setCapital] = useState(desgloseGuardado ? entero(cuota!.capital) : '')
  const [honorarios, setHonorarios] = useState(desgloseGuardado ? entero(cuota!.honorarios) : '0')
  const [interes, setInteres] = useState(desgloseGuardado ? entero(cuota!.intereses) : '0')
  const [gastos, setGastos] = useState(desgloseGuardado
    ? String(Math.round(Number(cuota!.gastos_judiciales ?? 0) + Number(cuota!.comision ?? 0))) : '0')
  const [origen, setOrigen] = useState(desgloseGuardado ? 'Desglose de la cuota según el acuerdo.' : '')
  const [error, setError] = useState('')
  const { data: uf } = useUF(fecha < fechaLocal() ? fecha : undefined)

  // Desglose automático cuando cambia el total (salvo que se esté editando
  // a mano o la cuota ya traiga su desglose y el total sea el de la cuota).
  useEffect(() => {
    if (editando) return
    const monto = Number(total)
    if (!(monto > 0)) return
    if (desgloseGuardado && monto === Math.round(saldoCuota)) return
    if (!conCalculadora || (modalidad === 'extrajudicial' && !uf)) {
      setCapital(String(monto)); setHonorarios('0'); setInteres('0'); setGastos('0')
      setOrigen('Todo el monto va a capital. Usa "Editar desglose" si incluye honorarios o interés.')
      return
    }
    const t = setTimeout(() => {
      api.post<ResultadoHonorarios>('/calculadora/abono', {
        abono: monto, modalidad, uf: modalidad === 'extrajudicial' ? uf?.valor : null,
      }).then(({ data }) => {
        setCapital(entero(data.capital)); setHonorarios(entero(data.total_honorarios))
        setInteres('0'); setGastos('0')
        setOrigen(modalidad === 'judicial'
          ? 'Separado con el porcentaje judicial.'
          : `Separado con la tabla 3-6-9 (UF ${Number(uf!.valor).toLocaleString('es-CL')}).`)
      }).catch(() => {
        setCapital(String(monto)); setHonorarios('0')
        setOrigen('No se pudo calcular el 3-6-9: todo va a capital.')
      })
    }, 350)
    return () => clearTimeout(t)
  }, [total, editando, conCalculadora, modalidad, uf, desgloseGuardado, saldoCuota])

  const monto = Number(total) || 0
  const suma = (Number(capital) || 0) + (Number(honorarios) || 0) + (Number(interes) || 0) + (Number(gastos) || 0)
  const cuadra = Math.round(suma) === Math.round(monto)

  const pagar = useMutation({
    mutationFn: async () => {
      await api.post('/pagos/', {
        cobranza_id: cobranzaId,
        cuota_id: cuota?.id ?? null,
        fecha_pago: fecha,
        monto: String(monto),
        capital: capital || '0',
        honorarios: honorarios || '0',
        intereses: interes || '0',
        gastos_judiciales: gastos || '0',
        forma_pago: forma,
        numero_comprobante: comprobante || null,
        observaciones: comentario.trim() || null,
        estado_pago: cuota ? 'cuota' : 'abono',
      })
    },
    onSuccess: () => alTerminar({
      monto, capital: Number(capital) || 0, honorarios: Number(honorarios) || 0,
      intereses: Number(interes) || 0, gastos: Number(gastos) || 0, fecha,
      cuota: cuota?.numero_cuota ?? null,
    }),
    onError: (err) => setError(mensajeDeError(err)),
  })

  function alEnviar(e: FormEvent) {
    e.preventDefault()
    setError('')
    if (!cuadra) { setError('El desglose debe sumar exactamente el monto recibido.'); return }
    pagar.mutate()
  }

  return (
    <form className="form-finanzas form-pago" onSubmit={alEnviar}>
      <h3>{cuota ? `Pago de la cuota ${cuota.numero_cuota}` : 'Abono'}</h3>
      <div className="fila">
        <label className="campo-destacado">
          Monto recibido *
          <input type="number" min="1" value={total} onChange={(e) => setTotal(e.target.value)}
            required autoFocus placeholder="$" />
        </label>
        <label>
          Fecha del pago
          <input type="date" value={fecha} max={fechaLocal()} onChange={(e) => setFecha(e.target.value)} required />
        </label>
        <label>
          Forma de pago
          <select value={forma} onChange={(e) => setForma(e.target.value)}>
            {FORMAS_PAGO.map((f) => <option key={f} value={f}>{NOMBRE_FORMA[f]}</option>)}
          </select>
        </label>
        <label>
          N° comprobante
          <input value={comprobante} onChange={(e) => setComprobante(e.target.value)} placeholder="opcional" />
        </label>
      </div>

      {monto > 0 && (
        <div className="desglose">
          {editando ? (
            <div className="fila">
              <label>Capital *<input type="number" min="0" value={capital} onChange={(e) => setCapital(e.target.value)} /></label>
              <label>Honorarios<input type="number" min="0" value={honorarios} onChange={(e) => setHonorarios(e.target.value)} /></label>
              <label>Interés<input type="number" min="0" value={interes} onChange={(e) => setInteres(e.target.value)} /></label>
              <label>Gastos<input type="number" min="0" value={gastos} onChange={(e) => setGastos(e.target.value)} /></label>
            </div>
          ) : (
            <div className="desglose-resumen">
              <span>Capital <strong><Plata valor={capital || 0} /></strong></span>
              {Number(honorarios) > 0 && <span>Honorarios <strong><Plata valor={honorarios} /></strong></span>}
              {Number(interes) > 0 && <span>Interés <strong><Plata valor={interes} /></strong></span>}
              {Number(gastos) > 0 && <span>Gastos <strong><Plata valor={gastos} /></strong></span>}
            </div>
          )}
          <div className="desglose-pie">
            <span className="suave">{editando ? 'Desglose a mano.' : origen}</span>
            <button type="button" className="btn btn-chico btn-secundario" onClick={() => setEditando(!editando)}>
              {editando ? 'Volver al automático' : 'Editar desglose'}
            </button>
          </div>
          {!cuadra && (
            <div className="alerta-error">
              El desglose suma <Plata valor={suma} /> y el monto es <Plata valor={monto} />
              {' '}(diferencia <Plata valor={monto - suma} />).
            </div>
          )}
        </div>
      )}

      <label className="campo-ancho">
        Comentario (opcional)
        <input value={comentario} onChange={(e) => setComentario(e.target.value)} maxLength={500}
          placeholder="Ej.: pagó en la oficina, envió comprobante por WhatsApp…" />
      </label>
      <p className="nota">
        Solo el capital descuenta el saldo. El pago entra al recupero del mes y queda en el historial
        junto con tu comentario.
      </p>
      {error && <div className="alerta-error">{error}</div>}
      <div className="fila">
        <button className="btn btn-primario" disabled={pagar.isPending || monto <= 0 || !cuadra}>
          {pagar.isPending ? 'Registrando…' : `Registrar ${cuota ? 'pago' : 'abono'} de ${monto > 0 ? '$' + Math.round(monto).toLocaleString('es-CL') : ''}`}
        </button>
        <button type="button" className="btn btn-secundario" onClick={alCancelar}>Cancelar</button>
      </div>
    </form>
  )
}

export const NOMBRE_FORMA: Record<string, string> = {
  transferencia: 'Transferencia', cheque: 'Cheque', efectivo: 'Efectivo', deposito: 'Depósito',
  flow: 'Pago en línea', presencial: 'Presencial', bonificacion: 'Bonificación', otro: 'Otro',
}

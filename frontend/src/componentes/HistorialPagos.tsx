import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, mensajeDeError } from '../api/client'
import { refrescarCaso } from '../api/refrescar'
import { useAuth } from '../auth'
import type { Pago } from '../api/tipos'
import { cierreDeFondo, fechaHoraLegible, fechaLegible, NOMBRE_FORMA, nombreCuota, Plata } from './utiles'

// Cuánto debía al llegar, cuánto ha pagado y cuánto debe hoy, con el
// historial de pagos a un clic: solo los pagos, con su fecha, y al abrir uno
// su desglose (capital, honorarios, interés, gastos, comprobante…).
// Un pago mal ingresado se ANULA (no se borra): queda tachado con su motivo,
// fuera de los totales, y su gestión original sigue en el historial.

const vigente = (p: Pago) => !p.anulado_at

export function usePagos(filtro: { deudor_id?: string; cobranza_id?: string }) {
  const clave = filtro.deudor_id ? ['pagos-deudor', filtro.deudor_id] : ['pagos', filtro.cobranza_id]
  return useQuery({
    queryKey: clave,
    enabled: Boolean(filtro.deudor_id || filtro.cobranza_id),
    queryFn: async () => (await api.get<Pago[]>('/pagos/', { params: { ...filtro, limit: 500 } })).data,
  })
}

export function ResumenDeuda({ original, saldo, pagos, alAbonar, enlaceAbonar, deudorId, cobranzaId, alVerHistorial,
  nombreAbonar = 'Registrar abono' }: {
  original: number
  saldo: number
  pagos: Pago[] | undefined
  alAbonar?: () => void
  enlaceAbonar?: string
  deudorId?: string
  cobranzaId?: string
  /** Si se da, "Historial de pagos" lleva ahí (la pestaña de pagos de la ficha) en vez de abrir la ventana. */
  alVerHistorial?: () => void
  nombreAbonar?: string
}) {
  const [historial, setHistorial] = useState(false)
  const validos = (pagos ?? []).filter(vigente)
  const pagado = validos.reduce((s, p) => s + Number(p.monto), 0)
  const avance = original > 0 ? Math.min(100, Math.round(((original - saldo) / original) * 100)) : 0
  return (
    <section className="resumen-deuda" aria-label="Resumen de la deuda">
      <div className="resumen-deuda-cifra">
        <span className="suave">Llegó con</span>
        <strong><Plata valor={original} /></strong>
      </div>
      <div className="resumen-deuda-cifra">
        <span className="suave">Ha pagado</span>
        <strong className="texto-verde"><Plata valor={pagado} /></strong>
        <span className="suave">{validos.length} pago{validos.length === 1 ? '' : 's'}</span>
      </div>
      <div className="resumen-deuda-cifra">
        <span className="suave">Debe hoy</span>
        <strong className={saldo > 0 ? 'texto-rojo-fuerte' : 'texto-verde'}><Plata valor={saldo} /></strong>
        <span className="medidor" title={`${avance} % del capital recuperado`}><span style={{ width: `${avance}%` }} /></span>
      </div>
      <div className="resumen-deuda-acciones">
        <button className="btn btn-secundario btn-chico" onClick={() => (alVerHistorial ? alVerHistorial() : setHistorial(true))}
          disabled={!pagos || pagos.length === 0}>
          Historial de pagos
        </button>
        {alAbonar && <button className="btn btn-primario btn-chico" onClick={alAbonar}>{nombreAbonar}</button>}
        {enlaceAbonar && <Link className="btn btn-primario btn-chico" to={enlaceAbonar}>{nombreAbonar}</Link>}
      </div>
      {historial && (
        <HistorialPagos deudorId={deudorId} cobranzaId={cobranzaId} alCerrar={() => setHistorial(false)} />
      )}
    </section>
  )
}

export default function HistorialPagos({ deudorId, cobranzaId, alCerrar }: {
  deudorId?: string; cobranzaId?: string; alCerrar: () => void
}) {
  const { data: pagos } = usePagos(deudorId ? { deudor_id: deudorId } : { cobranza_id: cobranzaId })
  const total = (pagos ?? []).filter(vigente).reduce((s, p) => s + Number(p.monto), 0)

  useEffect(() => {
    const tecla = (e: KeyboardEvent) => { if (e.key === 'Escape') alCerrar() }
    document.addEventListener('keydown', tecla)
    return () => document.removeEventListener('keydown', tecla)
  }, [alCerrar])

  return (
    <div className="modal-fondo" {...cierreDeFondo(alCerrar)}>
      <div className="modal modal-ancho" role="dialog" aria-label="Historial de pagos" onClick={(e) => e.stopPropagation()}>
        <div className="tarjeta-cabecera">
          <h3>Historial de pagos</h3>
          <span>Total pagado: <strong><Plata valor={total} /></strong></span>
        </div>
        <ListaPagos deudorId={deudorId} cobranzaId={cobranzaId} alNavegar={alCerrar} />
        <div className="acciones-fila">
          <button className="btn btn-secundario" onClick={alCerrar}>Cerrar</button>
        </div>
      </div>
    </div>
  )
}

/** Los pagos con su fecha; al abrir uno, su desglose y (con permiso) "Anular este pago". */
export function ListaPagos({ deudorId, cobranzaId, alNavegar }: {
  deudorId?: string; cobranzaId?: string; alNavegar?: () => void
}) {
  const { data: pagos, isLoading } = usePagos(deudorId ? { deudor_id: deudorId } : { cobranza_id: cobranzaId })
  const [abierto, setAbierto] = useState<string | null>(null)
  if (isLoading) return <p className="suave">Cargando…</p>
  return (
    <ul className="historial-pagos">
      {pagos?.map((p) => {
        const abiertoEste = abierto === p.id
        return (
          <li key={p.id} className={[abiertoEste ? 'abierto' : '', p.anulado_at ? 'pago-anulado' : ''].join(' ')}>
            <button className="historial-pago" aria-expanded={abiertoEste}
              onClick={() => setAbierto(abiertoEste ? null : p.id)}>
              <span className="historial-fecha">{fechaLegible(p.fecha_pago)}</span>
              <span className="historial-detalle">
                {p.numero_cuota != null ? nombreCuota(p.numero_cuota, null, 'Cuota ') : p.estado_pago === 'abono' ? 'Abono' : 'Pago'}
                {deudorId && p.numero_cobranza && ` · Cobranza N° ${p.numero_cobranza}`}
                {p.forma_pago && ` · ${NOMBRE_FORMA[p.forma_pago] ?? p.forma_pago}`}
                {p.anulado_at && <span className="etiqueta etiqueta-castigo">Anulado</span>}
              </span>
              <strong className="historial-monto"><Plata valor={p.monto} /></strong>
            </button>
            {abiertoEste && (
              <dl className="datos historial-desglose">
                <dt>Capital</dt><dd><Plata valor={p.capital} /></dd>
                {Number(p.honorarios) > 0 && <><dt>Honorarios</dt><dd><Plata valor={p.honorarios} /></dd></>}
                {Number(p.intereses) > 0 && <><dt>Interés</dt><dd><Plata valor={p.intereses} /></dd></>}
                {Number(p.gastos_judiciales) > 0 && <><dt>Gastos</dt><dd><Plata valor={p.gastos_judiciales} /></dd></>}
                {p.numero_comprobante && <><dt>Comprobante</dt><dd className="mono">{p.numero_comprobante}</dd></>}
                {p.usuario_nombre && <><dt>Registró</dt><dd>{p.usuario_nombre}{p.created_at && ` · ${fechaHoraLegible(p.created_at)}`}</dd></>}
                {p.observaciones && <><dt>Comentario</dt><dd>{p.observaciones}</dd></>}
                {deudorId && <><dt>Cobranza</dt><dd><Link to={`/cobranzas/${p.cobranza_id}`} onClick={alNavegar}>Ver cobranza N° {p.numero_cobranza}</Link></dd></>}
                {p.anulado_at && (
                  <><dt>Anulado</dt><dd>{fechaHoraLegible(p.anulado_at)}{p.anulado_por_nombre && ` por ${p.anulado_por_nombre}`}
                    {p.motivo_anulacion && <div className="suave">Motivo: {p.motivo_anulacion}</div>}</dd></>
                )}
              </dl>
            )}
            {abiertoEste && !p.anulado_at && <AnularPago pago={p} />}
          </li>
        )
      })}
      {pagos?.length === 0 && <li className="vacio">Aún no hay pagos registrados.</li>}
    </ul>
  )
}

function AnularPago({ pago }: { pago: Pago }) {
  const { puede } = useAuth()
  const qc = useQueryClient()
  const [abierto, setAbierto] = useState(false)
  const [motivo, setMotivo] = useState('')
  const [listo, setListo] = useState(false)
  const anular = useMutation({
    mutationFn: () => api.post(`/pagos/${pago.id}/anular`, { motivo: motivo.trim() }),
    onSuccess: () => {
      setListo(true)
      refrescarCaso(qc, pago.cobranza_id)
      qc.invalidateQueries({ queryKey: ['pagos-deudor'] })
    },
  })
  if (!puede('pagos_anular')) return null
  if (listo) {
    return <div className="alerta-exito">Pago anulado. Si estaba mal ingresado, registra ahora el pago correcto.</div>
  }
  if (!abierto) {
    return <button className="btn btn-chico btn-peligro anular-pago" onClick={() => setAbierto(true)}>Anular este pago</button>
  }
  return (
    <form className="form-anular" onSubmit={(e: FormEvent) => { e.preventDefault(); anular.mutate() }}>
      <p className="nota">
        El pago no se borra: queda tachado y fuera de los totales, el saldo vuelve atrás y su gestión
        original se mantiene. Se agrega una gestión con el motivo.
      </p>
      <label>
        Motivo *
        <input value={motivo} onChange={(e) => setMotivo(e.target.value)} required minLength={3} maxLength={500} autoFocus
          placeholder="Ej.: monto mal digitado, era $45.000" />
      </label>
      {anular.error && <div className="alerta-error">{mensajeDeError(anular.error)}</div>}
      <div className="acciones-fila">
        <button className="btn btn-chico btn-peligro" disabled={anular.isPending || motivo.trim().length < 3}>
          {anular.isPending ? 'Anulando…' : 'Anular pago'}
        </button>
        <button type="button" className="btn btn-chico btn-secundario" onClick={() => setAbierto(false)}>Cancelar</button>
      </div>
    </form>
  )
}


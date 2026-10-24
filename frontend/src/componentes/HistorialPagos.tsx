import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Pago } from '../api/tipos'
import { Plata, fechaHoraLegible, fechaLegible, nombreCuota } from './utiles'
import { NOMBRE_FORMA } from './Finanzas'

// Cuánto debía al llegar, cuánto ha pagado y cuánto debe hoy, con el
// historial de pagos a un clic: solo los pagos, con su fecha, y al abrir uno
// su desglose (capital, honorarios, interés, gastos, comprobante…).

export function usePagos(filtro: { deudor_id?: string; cobranza_id?: string }) {
  const clave = filtro.deudor_id ? ['pagos-deudor', filtro.deudor_id] : ['pagos', filtro.cobranza_id]
  return useQuery({
    queryKey: clave,
    enabled: Boolean(filtro.deudor_id || filtro.cobranza_id),
    queryFn: async () => (await api.get<Pago[]>('/pagos/', { params: { ...filtro, limit: 500 } })).data,
  })
}

export function ResumenDeuda({ original, saldo, pagos, alAbonar, enlaceAbonar, deudorId, cobranzaId }: {
  original: number
  saldo: number
  pagos: Pago[] | undefined
  alAbonar?: () => void
  enlaceAbonar?: string
  deudorId?: string
  cobranzaId?: string
}) {
  const [historial, setHistorial] = useState(false)
  const pagado = (pagos ?? []).reduce((s, p) => s + Number(p.monto), 0)
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
        <span className="suave">{pagos?.length ?? 0} pago{pagos?.length === 1 ? '' : 's'}</span>
      </div>
      <div className="resumen-deuda-cifra">
        <span className="suave">Debe hoy</span>
        <strong className={saldo > 0 ? 'texto-rojo-fuerte' : 'texto-verde'}><Plata valor={saldo} /></strong>
        <span className="medidor" title={`${avance} % del capital recuperado`}><span style={{ width: `${avance}%` }} /></span>
      </div>
      <div className="resumen-deuda-acciones">
        <button className="btn btn-secundario btn-chico" onClick={() => setHistorial(true)}
          disabled={!pagos || pagos.length === 0}>
          Historial de pagos
        </button>
        {alAbonar && <button className="btn btn-primario btn-chico" onClick={alAbonar}>Registrar abono</button>}
        {enlaceAbonar && <Link className="btn btn-primario btn-chico" to={enlaceAbonar}>Registrar abono</Link>}
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
  const { data: pagos, isLoading } = usePagos(deudorId ? { deudor_id: deudorId } : { cobranza_id: cobranzaId })
  const [abierto, setAbierto] = useState<string | null>(null)
  const total = (pagos ?? []).reduce((s, p) => s + Number(p.monto), 0)

  useEffect(() => {
    const tecla = (e: KeyboardEvent) => { if (e.key === 'Escape') alCerrar() }
    document.addEventListener('keydown', tecla)
    return () => document.removeEventListener('keydown', tecla)
  }, [alCerrar])

  return (
    <div className="modal-fondo" onClick={alCerrar}>
      <div className="modal modal-ancho" role="dialog" aria-label="Historial de pagos" onClick={(e) => e.stopPropagation()}>
        <div className="tarjeta-cabecera">
          <h3>Historial de pagos</h3>
          <span>Total pagado: <strong><Plata valor={total} /></strong></span>
        </div>
        {isLoading ? <p className="suave">Cargando…</p> : (
          <ul className="historial-pagos">
            {pagos?.map((p) => {
              const abiertoEste = abierto === p.id
              return (
                <li key={p.id} className={abiertoEste ? 'abierto' : ''}>
                  <button className="historial-pago" aria-expanded={abiertoEste}
                    onClick={() => setAbierto(abiertoEste ? null : p.id)}>
                    <span className="historial-fecha">{fechaLegible(p.fecha_pago)}</span>
                    <span className="historial-detalle">
                      {p.numero_cuota != null ? nombreCuota(p.numero_cuota, null, 'Cuota ') : p.estado_pago === 'abono' ? 'Abono' : 'Pago'}
                      {deudorId && p.numero_cobranza && ` · Cobranza N° ${p.numero_cobranza}`}
                      {p.forma_pago && ` · ${NOMBRE_FORMA[p.forma_pago] ?? p.forma_pago}`}
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
                      {deudorId && <><dt>Cobranza</dt><dd><Link to={`/cobranzas/${p.cobranza_id}`} onClick={alCerrar}>Ver cobranza N° {p.numero_cobranza}</Link></dd></>}
                    </dl>
                  )}
                </li>
              )
            })}
            {pagos?.length === 0 && <li className="vacio">Aún no hay pagos registrados.</li>}
          </ul>
        )}
        <div className="acciones-fila">
          <button className="btn btn-secundario" onClick={alCerrar}>Cerrar</button>
        </div>
      </div>
    </div>
  )
}

import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, mensajeDeError } from '../api/client'
import type { CicloVida as Ciclo, PasoCiclo } from '../api/judicial'
import type { CobranzaDetalle } from '../api/tipos'
import { useAuth } from '../auth'
import { fechaLegible } from './utiles'
import NuevaDemanda from './NuevaDemanda'

// Barra con el ciclo de vida de la cobranza: de dónde viene, en qué etapa
// está y qué le queda. Debajo, el dato clave de la etapa y la acción que la
// hace avanzar (preparar la demanda, presentarla, ir a la causa).

const NOMBRE_ETAPA: Record<string, string> = {
  ingreso: 'Ingreso',
  extrajudicial: 'Extrajudicial',
  para_demanda: 'Preparación de demanda',
  judicial: 'Judicial',
}

function Paso({ paso, numero, inicio, anterior }: {
  paso: PasoCiclo; numero: number; inicio: boolean; anterior?: PasoCiclo
}) {
  // La línea que llega desde un paso saltado va punteada.
  const desdeOmitido = anterior?.estado === 'omitido' ? ' desde-omitido' : ''
  return (
    <li className={`ciclo-paso ${paso.estado}${inicio ? ' inicio' : ''}${desdeOmitido}`}
      aria-current={paso.estado === 'actual' ? 'step' : undefined}>
      <span className="ciclo-punto">{numero}</span>
      <span className="ciclo-nombre">{paso.nombre}</span>
    </li>
  )
}

export function BarraCiclo({ pasos }: { pasos: PasoCiclo[] }) {
  const judiciales = pasos.filter((p) => p.grupo === 'judicial')
  const antes = pasos.slice(0, pasos.indexOf(judiciales[0]))
  const despues = pasos.slice(pasos.indexOf(judiciales[judiciales.length - 1]) + 1)
  const enJudicial = judiciales.some((p) => p.estado === 'actual' || p.estado === 'hecho')
  const lista = useRef<HTMLOListElement>(null)
  // En pantallas angostas la barra se desplaza: se centra en el paso actual.
  useEffect(() => {
    const ol = lista.current
    const actual = ol?.querySelector<HTMLElement>('.ciclo-paso.actual')
    if (!ol || !actual || ol.scrollWidth <= ol.clientWidth) return
    const centro = actual.getBoundingClientRect().left - ol.getBoundingClientRect().left + ol.scrollLeft
    ol.scrollLeft = centro - ol.clientWidth / 2 + actual.offsetWidth / 2
  }, [pasos])
  let n = 0
  const previo = (p: PasoCiclo) => pasos[pasos.indexOf(p) - 1]
  return (
    <ol className="ciclo-pasos con-grupo" ref={lista}>
      {antes.map((p, i) => <Paso key={p.clave} paso={p} numero={++n} inicio={i === 0} anterior={previo(p)} />)}
      <li className={`ciclo-grupo${enJudicial ? ' activo' : ''}`}>
        <span className="ciclo-grupo-nombre">Judicial</span>
        <ol className="ciclo-pasos">
          {judiciales.map((p) => <Paso key={p.clave} paso={p} numero={++n} inicio={false} anterior={previo(p)} />)}
        </ol>
      </li>
      {despues.map((p) => <Paso key={p.clave} paso={p} numero={++n} inicio={false} anterior={previo(p)} />)}
    </ol>
  )
}

export default function CicloVida({ cobranza }: { cobranza: CobranzaDetalle }) {
  const { tiene } = useAuth()
  const qc = useQueryClient()
  const [demanda, setDemanda] = useState(false)
  const [error, setError] = useState('')
  const judicial = tiene('judicial')

  const { data: ciclo } = useQuery({
    queryKey: ['ciclo', cobranza.id],
    queryFn: async () => (await api.get<Ciclo>(`/cobranzas/${cobranza.id}/ciclo`)).data,
  })

  const mover = useMutation({
    mutationFn: async (etapa: 'extrajudicial' | 'para_demanda') => {
      const motivo = etapa === 'para_demanda'
        ? window.prompt('¿Por qué se prepara la demanda? (opcional)', 'No responde a la cobranza extrajudicial')
        : window.prompt('¿Por qué vuelve a extrajudicial? (opcional)', '')
      if (motivo === null) return null
      return (await api.post<Ciclo>(`/cobranzas/${cobranza.id}/etapa`, { etapa, motivo: motivo || null })).data
    },
    onSuccess: (d) => {
      if (!d) return
      setError('')
      qc.setQueryData(['ciclo', cobranza.id], d)
      qc.invalidateQueries({ queryKey: ['cobranza', cobranza.id] })
    },
    onError: (e) => setError(mensajeDeError(e)),
  })

  if (!ciclo) return <section className="ciclo ciclo-cargando" aria-busy="true" />

  const cerrada = ciclo.paso_actual === 'termino'
  const causaVigente = ciclo.causas.find((c) => c.estado === 'vigente')
  const ultimoCambio = ciclo.historial[ciclo.historial.length - 1]

  return (
    <section className="ciclo" aria-label="Ciclo de vida de la cobranza">
      <BarraCiclo pasos={ciclo.pasos} />

      <div className="ciclo-pie">
        <div className="ciclo-estado">
          {cerrada ? (
            <>
              <strong>Terminada: {ciclo.motivo_cierre_nombre ?? ciclo.estado}</strong>
              {ciclo.fecha_cierre && <span className="suave"> el {fechaLegible(ciclo.fecha_cierre)}</span>}
            </>
          ) : (
            <>
              <strong>{NOMBRE_ETAPA[ciclo.etapa]}</strong>
              <span className="suave">
                {' '}desde el {fechaLegible(ciclo.etapa_desde)}
                {ciclo.dias_en_etapa != null && ` (${ciclo.dias_en_etapa} día${ciclo.dias_en_etapa === 1 ? '' : 's'})`}
              </span>
              {ultimoCambio?.motivo && ciclo.etapa !== 'ingreso' && (
                <span className="suave"> · {ultimoCambio.motivo}</span>
              )}
            </>
          )}
          {ciclo.causas.map((c) => (
            <div key={c.id} className="ciclo-causa">
              Causa {c.rol ? `rol ${c.rol}` : 'sin rol aún'}
              {c.tribunal && <span className="suave"> · {c.tribunal}</span>}
              {c.estado === 'terminada' && <span className="etiqueta etiqueta-archivada">terminada</span>}
              {judicial && <Link to={`/judicial/causas/${c.id}`}>Ver causa</Link>}
            </div>
          ))}
          {ciclo.prescripcion_proxima && ciclo.fecha_prescripcion && (
            <div className="ciclo-alerta">
              La acción podría prescribir el {fechaLegible(ciclo.fecha_prescripcion)}: conviene demandar antes.
            </div>
          )}
          {error && <div className="alerta-error">{error}</div>}
        </div>

        {!cerrada && judicial && (
          <div className="ciclo-acciones">
            {(ciclo.etapa === 'ingreso' || ciclo.etapa === 'extrajudicial') && (
              <button className="btn btn-secundario btn-chico" disabled={mover.isPending}
                onClick={() => mover.mutate('para_demanda')}>
                Preparar demanda
              </button>
            )}
            {ciclo.etapa === 'para_demanda' && (
              <>
                <button className="btn btn-primario btn-chico" onClick={() => setDemanda(true)}>
                  Presentar demanda
                </button>
                <button className="btn btn-secundario btn-chico" disabled={mover.isPending}
                  onClick={() => mover.mutate('extrajudicial')}>
                  Volver a extrajudicial
                </button>
              </>
            )}
            {ciclo.etapa === 'judicial' && causaVigente && (
              <Link className="btn btn-primario btn-chico" to={`/judicial/causas/${causaVigente.id}`}>
                Registrar trámite
              </Link>
            )}
          </div>
        )}
      </div>

      {demanda && <NuevaDemanda cobranza={cobranza} alCerrar={() => setDemanda(false)} />}
    </section>
  )
}

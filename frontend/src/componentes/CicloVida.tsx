import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, mensajeDeError } from '../api/client'
import type { CicloVida as Ciclo, PasoCiclo } from '../api/judicial'
import type { CobranzaDetalle } from '../api/tipos'
import { useAuth } from '../auth'
import { fechaHoraLegible, fechaLegible } from './utiles'
import { useCatalogos } from './usarJudicial'
import NuevaDemanda from './NuevaDemanda'
import ConfirmarGestion from './ConfirmarGestion'

// Ciclo de vida de la cobranza: de dónde viene, en qué etapa está y qué le
// queda.
//  - CicloVida (arriba de la ficha, compacto): la etapa, cuánto lleva en ella,
//    el paso que sigue y la acción que la hace avanzar (preparar la demanda,
//    presentarla, ir a la causa). "Ver etapas" despliega la barra completa.
//  - DetalleCiclo (pestaña Judicial): la barra, las causas y los cambios de etapa.

// Como las nombra la gestión que deja el servidor.
const ETAPA_GESTION: Record<string, string> = {
  ingreso: 'Ingreso', extrajudicial: 'Extrajudicial', para_demanda: 'Para demanda', judicial: 'Judicial',
}

const NOMBRE_ETAPA: Record<string, string> = {
  ingreso: 'Ingreso',
  extrajudicial: 'Extrajudicial',
  para_demanda: 'Preparación de demanda',
  judicial: 'Judicial',
}

export function useCiclo(cobranzaId: string) {
  return useQuery({
    queryKey: ['ciclo', cobranzaId],
    queryFn: async () => (await api.get<Ciclo>(`/cobranzas/${cobranzaId}/ciclo`)).data,
  })
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

/** Puntos chicos, uno por paso: el camino de un vistazo (el detalle, en "Ver etapas"). */
function PuntosCiclo({ pasos }: { pasos: PasoCiclo[] }) {
  return (
    <ol className="ciclo-mini" aria-hidden="true">
      {pasos.map((p) => (
        <li key={p.clave} className={`${p.estado}${p.grupo === 'judicial' ? ' judicial' : ''}`} title={p.nombre} />
      ))}
    </ol>
  )
}

export default function CicloVida({ cobranza }: { cobranza: CobranzaDetalle }) {
  const { tiene, puede } = useAuth()
  const qc = useQueryClient()
  const [demanda, setDemanda] = useState(false)
  const [etapas, setEtapas] = useState(false)
  const [error, setError] = useState('')
  const judicial = tiene('judicial')
  const { data: ciclo } = useCiclo(cobranza.id)

  // Cambio de etapa: se confirma con su motivo (queda como gestión).
  const [moviendo, setMoviendo] = useState<'extrajudicial' | 'para_demanda' | null>(null)
  const [motivo, setMotivo] = useState('')
  const mover = useMutation({
    mutationFn: async (etapa: 'extrajudicial' | 'para_demanda') =>
      (await api.post<Ciclo>(`/cobranzas/${cobranza.id}/etapa`, { etapa, motivo: motivo.trim() || null })).data,
    onSuccess: (d) => {
      setMoviendo(null)
      setError('')
      qc.invalidateQueries({ queryKey: ['gestiones', cobranza.id] })
      qc.setQueryData(['ciclo', cobranza.id], d)
      qc.invalidateQueries({ queryKey: ['cobranza', cobranza.id] })
    },
    onError: (e) => setError(mensajeDeError(e)),
  })

  if (!ciclo) return <section className="ciclo ciclo-compacto ciclo-cargando" aria-busy="true" />

  const cerrada = ciclo.paso_actual === 'termino'
  const causaVigente = ciclo.causas.find((c) => c.estado === 'vigente')
  const ultimoCambio = ciclo.historial[ciclo.historial.length - 1]
  const iActual = ciclo.pasos.findIndex((p) => p.clave === ciclo.paso_actual)
  const siguiente = cerrada ? undefined : ciclo.pasos.slice(iActual + 1).find((p) => p.estado === 'pendiente')

  return (
    <section className="ciclo ciclo-compacto" aria-label="Ciclo de vida de la cobranza">
      <div className="ciclo-linea">
        <PuntosCiclo pasos={ciclo.pasos} />
        <div className="ciclo-texto">
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
              {siguiente && <span className="ciclo-siguiente"> · Sigue: {siguiente.nombre}</span>}
              {ultimoCambio?.motivo && ciclo.etapa !== 'ingreso' && (
                <span className="suave ciclo-motivo"> · {ultimoCambio.motivo}</span>
              )}
            </>
          )}
          {causaVigente && (
            <div className="ciclo-causa">
              Causa {causaVigente.rol ? `rol ${causaVigente.rol}` : 'sin rol aún'}
              {causaVigente.tribunal && <span className="suave"> · {causaVigente.tribunal}</span>}
            </div>
          )}
        </div>

        <div className="ciclo-acciones">
          {!cerrada && judicial && (ciclo.etapa === 'ingreso' || ciclo.etapa === 'extrajudicial') && (
            <button className="btn btn-secundario btn-chico" disabled={mover.isPending}
              onClick={() => { setMotivo('No responde a la cobranza extrajudicial'); setMoviendo('para_demanda') }}>
              {puede('judicial_causas') ? 'Preparar demanda' : 'Recomendar demanda'}
            </button>
          )}
          {!cerrada && judicial && ciclo.etapa === 'para_demanda' && (
            <>
              {puede('judicial_causas') && (
                <button className="btn btn-primario btn-chico" onClick={() => setDemanda(true)}>
                  Presentar demanda
                </button>
              )}
              <button className="btn btn-secundario btn-chico" disabled={mover.isPending}
                onClick={() => { setMotivo(''); setMoviendo('extrajudicial') }}>
                Volver a extrajudicial
              </button>
            </>
          )}
          {judicial && causaVigente && (
            <Link className={`btn btn-chico ${cerrada ? 'btn-secundario' : 'btn-primario'}`} to={`/judicial/causas/${causaVigente.id}`}>
              {cerrada ? 'Ver causa' : 'Registrar trámite'}
            </Link>
          )}
          <button type="button" className="btn-enlace" aria-expanded={etapas} onClick={() => setEtapas(!etapas)}>
            {etapas ? 'Ocultar etapas' : 'Ver etapas'}
          </button>
        </div>
      </div>

      {ciclo.prescripcion_proxima && ciclo.fecha_prescripcion && (
        <div className="ciclo-alerta">
          La acción podría prescribir el {fechaLegible(ciclo.fecha_prescripcion)}: conviene demandar antes.
        </div>
      )}
      {error && !moviendo && <div className="alerta-error">{error}</div>}
      {etapas && <div className="ciclo-desplegado"><BarraCiclo pasos={ciclo.pasos} /></div>}

      {demanda && <NuevaDemanda cobranza={cobranza} alCerrar={() => setDemanda(false)} />}
      {moviendo && (
        <ConfirmarGestion
          titulo={moviendo === 'para_demanda' ? 'Pasar a "Para demanda"' : 'Volver a extrajudicial'}
          detalle={(
            <label className="campo-ancho">
              {moviendo === 'para_demanda' ? '¿Por qué se prepara la demanda?' : '¿Por qué vuelve a extrajudicial?'}
              <input value={motivo} onChange={(e) => setMotivo(e.target.value)} maxLength={300} placeholder="Opcional" />
            </label>
          )}
          gestion={`CAMBIO DE ETAPA: ${ETAPA_GESTION[ciclo.etapa] ?? ciclo.etapa} → ${ETAPA_GESTION[moviendo]}`
            + (motivo.trim() ? `. Motivo: ${motivo.trim()}` : '') + '.'}
          confirmar="Sí, cambiar etapa"
          pendiente={mover.isPending}
          error={error}
          alConfirmar={() => mover.mutate(moviendo)}
          alCancelar={() => { setMoviendo(null); setError('') }}
        />
      )}
    </section>
  )
}

/** Pestaña Judicial de la ficha: la barra de etapas, las causas y los cambios de etapa. */
export function DetalleCiclo({ cobranzaId }: { cobranzaId: string }) {
  const { tiene } = useAuth()
  const { data: ciclo } = useCiclo(cobranzaId)
  const { data: catalogos } = useCatalogos()
  if (!ciclo) return <section className="tarjeta"><p className="suave">Cargando…</p></section>
  const cambios = [...ciclo.historial].reverse()

  return (
    <div className="detalle-ciclo">
      <section className="tarjeta">
        <h2>Etapas</h2>
        <BarraCiclo pasos={ciclo.pasos} />
        {ciclo.fecha_prescripcion && (
          <p className={ciclo.prescripcion_proxima ? 'ciclo-alerta' : 'nota'}>
            Prescripción estimada de la acción: {fechaLegible(ciclo.fecha_prescripcion)}.
          </p>
        )}
      </section>

      <section className="tarjeta">
        <h2>Causas ({ciclo.causas.length})</h2>
        {ciclo.causas.length === 0 ? (
          <p className="vacio">
            Aún no hay demanda.
            {ciclo.etapa === 'para_demanda' ? ' Se presenta con "Presentar demanda", arriba.'
              : ciclo.paso_actual !== 'termino' ? ' Cuando no responda a la cobranza, usa "Preparar demanda", arriba.' : ''}
          </p>
        ) : (
          <ul className="lista-causas">
            {ciclo.causas.map((c) => (
              <li key={c.id}>
                <div>
                  <strong>{c.rol ? `Rol ${c.rol}` : 'Sin rol aún'}</strong>
                  {c.tribunal && <span className="suave"> · {c.tribunal}</span>}
                  <span className={`etiqueta ${c.estado === 'vigente' ? 'etiqueta-judicial' : 'etiqueta-archivada'}`}>
                    {c.estado}
                  </span>
                </div>
                <div className="suave">
                  {catalogos?.procedimientos[c.procedimiento] ?? c.procedimiento}
                  {' · '}etapa {catalogos?.etapas[c.etapa_procesal] ?? c.etapa_procesal}
                  {' · '}ingresó el {fechaLegible(c.fecha_ingreso)}
                  {c.fecha_termino && ` · terminó el ${fechaLegible(c.fecha_termino)}`}
                  {c.resultado && ` · ${catalogos?.resultados[c.resultado] ?? c.resultado}`}
                </div>
                {tiene('judicial') && <Link to={`/judicial/causas/${c.id}`}>Ver causa y trámites</Link>}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="tarjeta">
        <h2>Cambios de etapa</h2>
        {cambios.length === 0 ? <p className="vacio">Sin cambios de etapa.</p> : (
          <ul className="lista-cambios-etapa">
            {cambios.map((h, i) => (
              <li key={`${h.created_at}-${i}`}>
                <span className="mono suave">{fechaHoraLegible(h.created_at)}</span>
                <span>
                  {h.etapa_anterior ? `${ETAPA_GESTION[h.etapa_anterior] ?? h.etapa_anterior} → ` : ''}
                  <strong>{ETAPA_GESTION[h.etapa_nueva] ?? h.etapa_nueva}</strong>
                  {h.motivo && <span className="suave"> · {h.motivo}</span>}
                  {h.usuario && <span className="suave"> · {h.usuario}</span>}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

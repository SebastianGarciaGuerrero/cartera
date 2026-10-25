import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Gestion, TipoGestion } from '../api/tipos'
import { fechaHoraLegible, fechaLegible } from './utiles'

// Historial de gestiones (de la más reciente a la más antigua) en una caja
// de alto fijo con su propio scroll, para que no estire la pantalla.

export default function LineaTiempo({ gestiones, cobranzas }: {
  gestiones: Gestion[] | undefined
  /** En la ficha del deudor: N° de cada cobranza, para enlazar cada gestión a la suya. */
  cobranzas?: Map<string, number>
}) {
  const { data: tipos } = useQuery({
    queryKey: ['tipos-gestion'],
    queryFn: async () => (await api.get<TipoGestion[]>('/gestiones/tipos')).data,
  })
  const tipo = (id: number | null) => tipos?.find((t) => t.id === id)
  // Las que deben saltar a la vista al recorrer el historial.
  const destacada = (id: number | null) => ['acuerdo', 'pagado', 'abono'].includes(tipo(id)?.codigo ?? '')

  return (
    <ul className="linea-tiempo linea-tiempo-scroll">
      {gestiones?.map((g) => (
        <li key={g.id} className={destacada(g.tipo_id) ? 'gestion-destacada' : ''}>
          <div className="gestion-cabecera">
            <span className="gestion-tipo">
              {tipo(g.tipo_id)?.nombre ?? 'Gestión'}
              {cobranzas?.has(g.cobranza_id) && (
                <Link className="gestion-cobranza" to={`/cobranzas/${g.cobranza_id}`}>N° {cobranzas.get(g.cobranza_id)}</Link>
              )}
            </span>
            <span className="suave">
              {g.usuario_nombre && (
                <span className="gestion-usuario">
                  {g.usuario_nombre}
                  {g.es_masivo && <span className="tag-masivo">masivo</span>}
                </span>
              )}
              {fechaHoraLegible(g.fecha_gestion)}
            </span>
          </div>
          <p>{g.descripcion}</p>
          {g.fecha_proximo_contacto && (
            <div className="proximo-aviso">Próximo contacto: {fechaLegible(g.fecha_proximo_contacto)}</div>
          )}
        </li>
      ))}
      {gestiones?.length === 0 && <li className="vacio">Aún no hay gestiones registradas.</li>}
    </ul>
  )
}

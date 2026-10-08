import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Avisos as DatosAvisos, ItemAgenda } from '../api/tipos'
import { fechaLegible } from './utiles'
import { ESTILO_TIPO } from '../paginas/Agenda'

// Campana de avisos: lo atrasado, lo de hoy y lo de mañana de la persona
// (cuotas que vencen de los acuerdos que registró o tiene asignados,
// promesas, próximos contactos y recordatorios). Se actualiza sola.

export function useAvisos(activo: boolean) {
  return useQuery({
    queryKey: ['avisos'],
    enabled: activo,
    queryFn: async () => (await api.get<DatosAvisos>('/agenda/avisos')).data,
    refetchInterval: 5 * 60 * 1000,
  })
}

export default function Avisos({ datos }: { datos: DatosAvisos | undefined }) {
  const [abierto, setAbierto] = useState(false)
  const caja = useRef<HTMLDivElement>(null)
  const pendientes = (datos?.atrasados.length ?? 0) + (datos?.hoy.length ?? 0)
  const total = pendientes + (datos?.manana.length ?? 0)

  // Se cierra con Escape o al hacer clic fuera.
  useEffect(() => {
    if (!abierto) return
    const fuera = (e: MouseEvent) => { if (!caja.current?.contains(e.target as Node)) setAbierto(false) }
    const tecla = (e: KeyboardEvent) => { if (e.key === 'Escape') setAbierto(false) }
    document.addEventListener('mousedown', fuera)
    document.addEventListener('keydown', tecla)
    return () => { document.removeEventListener('mousedown', fuera); document.removeEventListener('keydown', tecla) }
  }, [abierto])

  const cerrar = () => setAbierto(false)

  return (
    <div className="avisos" ref={caja}>
      <button className="avisos-boton" aria-expanded={abierto} onClick={() => setAbierto(!abierto)}
        aria-label={pendientes ? `Avisos: ${pendientes} pendiente(s)` : 'Avisos'} title="Avisos">
        <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="none" stroke="currentColor"
          strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.73 21a2 2 0 0 1-3.46 0" />
        </svg>
        {pendientes > 0 && <span className="avisos-contador">{pendientes > 99 ? '99+' : pendientes}</span>}
      </button>

      {abierto && (
        <div className="avisos-panel" role="dialog" aria-label="Avisos">
          <div className="avisos-cabecera">
            <strong>Avisos</strong>
            <Link to="/agenda" onClick={cerrar}>Ver agenda</Link>
          </div>
          {!datos ? <p className="suave">Cargando…</p> : total === 0 ? (
            <p className="suave">No tienes nada pendiente para hoy ni mañana.</p>
          ) : (
            <>
              <Grupo titulo="Atrasado" items={datos.atrasados} conFecha alElegir={cerrar} />
              <Grupo titulo="Hoy" items={datos.hoy} alElegir={cerrar} />
              <Grupo titulo="Mañana" items={datos.manana} alElegir={cerrar}
                nota="Buen momento para recordarle al deudor." />
            </>
          )}
        </div>
      )}
    </div>
  )
}

function Grupo({ titulo, items, conFecha, nota, alElegir }: {
  titulo: string; items: ItemAgenda[]; conFecha?: boolean; nota?: string; alElegir: () => void
}) {
  if (items.length === 0) return null
  return (
    <div className="avisos-grupo">
      <div className="avisos-grupo-titulo">{titulo} ({items.length}){nota && <span className="suave"> · {nota}</span>}</div>
      <ul>
        {items.slice(0, 30).map((i, n) => {
          const contenido = (
            <>
              <span className="agenda-punto" style={{ background: ESTILO_TIPO[i.tipo].color }} aria-hidden="true" />
              <span className="avisos-texto">
                <span>{i.titulo}</span>
                <span className="suave">
                  {ESTILO_TIPO[i.tipo].nombre}{conFecha && ` · ${fechaLegible(i.fecha)}`}{i.hora && ` · ${i.hora.slice(0, 5)}`}
                  {i.detalle && i.tipo === 'cuota' && ` · ${i.detalle}`}
                </span>
              </span>
            </>
          )
          return (
            <li key={`${i.tipo}-${i.cuota_id ?? i.recordatorio_id ?? i.cobranza_id}-${n}`}>
              {i.cobranza_id
                ? <Link to={`/cobranzas/${i.cobranza_id}`} onClick={alElegir}>{contenido}</Link>
                : <Link to="/agenda" onClick={alElegir}>{contenido}</Link>}
            </li>
          )
        })}
      </ul>
      {items.length > 30 && <p className="nota">Y {items.length - 30} más en la agenda.</p>}
    </div>
  )
}

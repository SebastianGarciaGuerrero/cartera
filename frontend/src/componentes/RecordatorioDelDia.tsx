import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import type { Avisos } from '../api/tipos'
import { fechaLocal } from './utiles'
import { ListaItems } from './BarraSuperior'

// Al entrar, una vez al día: lo que la persona tiene para hoy (promesas de
// pago, próximos contactos, cuotas, plazos judiciales y recordatorios) y lo
// que quedó atrasado. Sale de las gestiones que ella misma registró.

const clave = (usuarioId: string) => `cartera_recordatorio_${usuarioId}_${fechaLocal()}`

function yaVisto(usuarioId: string): boolean {
  try { return localStorage.getItem(clave(usuarioId)) === '1' } catch { return false }
}

function marcarVisto(usuarioId: string) {
  try { localStorage.setItem(clave(usuarioId), '1') } catch { /* modo privado */ }
}

export default function RecordatorioDelDia({ usuarioId, nombre, avisos }: {
  usuarioId: string; nombre: string; avisos: Avisos | undefined
}) {
  const [abierto, setAbierto] = useState(false)
  const hoy = avisos?.hoy ?? []
  const atrasados = avisos?.atrasados ?? []

  useEffect(() => {
    if (avisos && (hoy.length > 0 || atrasados.length > 0) && !yaVisto(usuarioId)) setAbierto(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [avisos, usuarioId])

  if (!abierto) return null
  const cerrar = () => { marcarVisto(usuarioId); setAbierto(false) }
  const primerNombre = nombre.split(/\s+/)[0]

  return (
    <div className="modal-fondo" onClick={cerrar}>
      <div className="modal modal-ancho recordatorio-dia" role="dialog" aria-label="Tus pendientes de hoy"
        onClick={(e) => e.stopPropagation()}>
        <h3>Hola, {primerNombre}. Esto tienes para hoy</h3>
        {hoy.length > 0 ? <ListaItems items={hoy} vacio="" alElegir={cerrar} />
          : <p className="suave">Nada agendado para hoy.</p>}
        {atrasados.length > 0 && (
          <>
            <div className="subtitulo">Quedó atrasado ({atrasados.length})</div>
            <ListaItems items={atrasados.slice(0, 8)} vacio="" alElegir={cerrar} />
            {atrasados.length > 8 && <p className="nota">Y {atrasados.length - 8} más en la agenda.</p>}
          </>
        )}
        <div className="acciones-fila">
          <Link className="btn btn-primario" to="/agenda" onClick={cerrar}>Ir a mi agenda</Link>
          <button className="btn btn-secundario" onClick={cerrar}>Entendido</button>
        </div>
      </div>
    </div>
  )
}

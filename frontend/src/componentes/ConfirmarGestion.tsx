import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import { useAuth } from '../auth'

// Antes de guardar un cambio: muestra la gestión que va a quedar en el
// historial a nombre de quien lo hace y pide confirmar. Todo cambio sobre
// una cobranza (abono, acuerdo, gasto, datos…) pasa por aquí.

export default function ConfirmarGestion({
  titulo, gestion, detalle, confirmar = 'Confirmar', pendiente = false, error, alConfirmar, alCancelar,
}: {
  titulo: string
  /** Texto de la gestión que se registrará. */
  gestion: string
  /** Resumen opcional del cambio (montos, datos). */
  detalle?: ReactNode
  confirmar?: string
  pendiente?: boolean
  error?: string
  alConfirmar: () => void
  alCancelar: () => void
}) {
  const { usuario } = useAuth()
  const boton = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    boton.current?.focus()
    const tecla = (e: KeyboardEvent) => { if (e.key === 'Escape' && !pendiente) alCancelar() }
    document.addEventListener('keydown', tecla)
    return () => document.removeEventListener('keydown', tecla)
  }, [alCancelar, pendiente])

  return (
    <div className="modal-fondo" onClick={() => !pendiente && alCancelar()}>
      <div className="modal confirmar-gestion" role="alertdialog" aria-modal="true" aria-labelledby="confirmar-titulo"
        onClick={(e) => e.stopPropagation()}>
        <h3 id="confirmar-titulo">{titulo}</h3>
        {detalle && <div className="confirmar-detalle">{detalle}</div>}
        <p className="suave confirmar-aviso">
          Quedará en el historial como gestión de <strong>{usuario?.nombre ?? 'tu usuario'}</strong>:
        </p>
        <blockquote className="confirmar-texto">{gestion}</blockquote>
        {error && <div className="alerta-error">{error}</div>}
        <div className="acciones-fila">
          <button ref={boton} type="button" className="btn btn-primario" disabled={pendiente} onClick={alConfirmar}>
            {pendiente ? 'Guardando…' : confirmar}
          </button>
          <button type="button" className="btn btn-secundario" disabled={pendiente} onClick={alCancelar}>Volver</button>
        </div>
      </div>
    </div>
  )
}

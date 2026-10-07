import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, mensajeDeError } from '../api/client'
import type { MensajePago as Mensaje, TipoGestion } from '../api/tipos'

// Mensaje de cobro listo para enviar: saldo + datos de transferencia del
// estudio (o del mandante). Se revisa/edita, se abre en WhatsApp o en el
// correo con el contacto del deudor ya puesto, y se registra la gestión.

type Canal = 'whatsapp' | 'email'

export default function MensajePago({ cobranzaId, alCerrar }: { cobranzaId: string; alCerrar: () => void }) {
  const qc = useQueryClient()
  const { data, error, isLoading } = useQuery({
    queryKey: ['mensaje-pago', cobranzaId],
    queryFn: async () => (await api.get<Mensaje>(`/cobranzas/${cobranzaId}/mensaje-pago`)).data,
  })
  const { data: tipos } = useQuery({
    queryKey: ['tipos-gestion'],
    queryFn: async () => (await api.get<TipoGestion[]>('/gestiones/tipos')).data,
  })
  const [texto, setTexto] = useState('')
  const [enviadoPor, setEnviadoPor] = useState<Canal | null>(null)
  const [copiado, setCopiado] = useState(false)
  useEffect(() => { if (data) setTexto(data.texto) }, [data])

  const registrar = useMutation({
    mutationFn: (canal: Canal) => api.post('/gestiones/', {
      cobranza_id: cobranzaId,
      tipo_id: tipos?.find((t) => t.codigo === canal)?.id ?? null,
      descripcion: `Mensaje de pago enviado por ${canal === 'whatsapp' ? 'WhatsApp' : 'correo'}:\n${texto}`,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['gestiones', cobranzaId] })
      alCerrar()
    },
  })

  function abrir(canal: Canal) {
    if (!data) return
    let url: string
    if (canal === 'whatsapp') {
      const numero = /wa\.me\/(\d*)/.exec(data.whatsapp_url ?? '')?.[1] ?? ''
      url = `https://wa.me/${numero}?text=${encodeURIComponent(texto)}`
    } else {
      url = `mailto:${encodeURIComponent(data.email ?? '')}?subject=${encodeURIComponent(data.asunto)}&body=${encodeURIComponent(texto)}`
    }
    window.open(url, '_blank', 'noopener')
    setEnviadoPor(canal)
  }

  return (
    <div className="modal-fondo" onClick={alCerrar}>
      <div className="modal modal-ancho" onClick={(e) => e.stopPropagation()}>
        <h3>Mensaje de pago</h3>
        {isLoading && <p className="suave">Preparando el mensaje…</p>}
        {error && <div className="alerta-error">{mensajeDeError(error)}</div>}
        {data && (
          <>
            {data.falta_datos_pago && (
              <div className="alerta-error">
                Faltan los datos de transferencia: cárgalos en Administración → Mi empresa
                (o en el cliente, si le pagan directo a él).
              </div>
            )}
            <textarea rows={12} value={texto} onChange={(e) => setTexto(e.target.value)} />
            <p className="suave">
              {data.telefono ? `WhatsApp: ${data.telefono}` : 'El deudor no tiene celular registrado.'}
              {' · '}
              {data.email ? `Correo: ${data.email}` : 'Sin correo registrado.'}
            </p>
            <div className="acciones">
              <button className="btn btn-primario" onClick={() => abrir('whatsapp')}>Abrir en WhatsApp</button>
              <button className="btn btn-secundario" onClick={() => abrir('email')}>Abrir en el correo</button>
              <button className="btn btn-secundario" onClick={() => {
                navigator.clipboard.writeText(texto); setCopiado(true)
              }}>{copiado ? 'Copiado ✓' : 'Copiar texto'}</button>
            </div>
            {enviadoPor && (
              <div className="alerta-exito">
                ¿Lo enviaste? Regístralo en el historial de la cobranza.{' '}
                <button className="btn btn-chico btn-primario" disabled={registrar.isPending}
                  onClick={() => registrar.mutate(enviadoPor)}>
                  Registrar gestión
                </button>
              </div>
            )}
          </>
        )}
        <div className="fila">
          <button className="btn btn-secundario" onClick={alCerrar}>Cerrar</button>
        </div>
      </div>
    </div>
  )
}

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, mensajeDeError } from '../api/client'
import type { EnlaceDeudor as Enlace, EnlaceDeudorNuevo, TipoGestion } from '../api/tipos'
import { fechaHoraLegible, fechaLegible } from './utiles'

// Enlace personal para que el deudor vea su estado (portal del deudor).
// El token se muestra una sola vez, al generarlo: después solo se ve si
// está vigente y cuántas veces lo abrió el deudor.

type Canal = 'whatsapp' | 'email'

export default function EnlaceDeudor({ deudorId, deudorNombre, cobranzaId, alCerrar }: {
  deudorId: string; deudorNombre: string; cobranzaId: string; alCerrar: () => void
}) {
  const qc = useQueryClient()
  const [nuevo, setNuevo] = useState<EnlaceDeudorNuevo | null>(null)
  const [copiado, setCopiado] = useState('')
  const [enviadoPor, setEnviadoPor] = useState<Canal | null>(null)
  const [error, setError] = useState('')

  const { data: vigente, isLoading } = useQuery({
    queryKey: ['enlace-deudor', deudorId],
    queryFn: async () => (await api.get<Enlace | null>(`/deudores/${deudorId}/enlace`)).data,
  })
  const { data: tipos } = useQuery({
    queryKey: ['tipos-gestion'],
    queryFn: async () => (await api.get<TipoGestion[]>('/gestiones/tipos')).data,
  })
  const refrescar = () => qc.invalidateQueries({ queryKey: ['enlace-deudor', deudorId] })

  const generar = useMutation({
    mutationFn: async () => (await api.post<EnlaceDeudorNuevo>(`/deudores/${deudorId}/enlace`)).data,
    onSuccess: (d) => { setNuevo(d); setCopiado(''); setEnviadoPor(null); setError(''); refrescar() },
    onError: (e) => setError(mensajeDeError(e)),
  })
  const desactivar = useMutation({
    mutationFn: () => api.delete(`/deudores/${deudorId}/enlace`),
    onSuccess: () => { setNuevo(null); refrescar() },
    onError: (e) => setError(mensajeDeError(e)),
  })
  const registrar = useMutation({
    mutationFn: (canal: Canal) => api.post('/gestiones/', {
      cobranza_id: cobranzaId,
      tipo_id: tipos?.find((t) => t.codigo === canal)?.id ?? null,
      descripcion: `Se envía al deudor el enlace a su estado de cuenta en línea por ${canal === 'whatsapp' ? 'WhatsApp' : 'correo'}.`,
    }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['gestiones', cobranzaId] }); alCerrar() },
  })

  function copiar(texto: string, que: string) {
    navigator.clipboard.writeText(texto)
    setCopiado(que)
  }

  const activo = nuevo ?? vigente

  return (
    <div className="modal-fondo" onClick={alCerrar}>
      <div className="modal modal-ancho" onClick={(e) => e.stopPropagation()}>
        <h3>Enlace para el deudor</h3>
        <p className="suave">
          {deudorNombre} verá el estado de sus deudas y de su convenio: cuotas pagadas y atrasadas,
          próxima cuota, sus pagos y cómo pagar. Para abrirlo tendrá que escribir su RUT.
          No ve gestiones, notas internas, honorarios ni nombres del equipo.
        </p>

        {isLoading ? <p className="suave">Cargando…</p> : nuevo ? (
          <>
            <div className="alerta-exito">
              Enlace creado. Envíalo ahora: por seguridad no se vuelve a mostrar (si se pierde, genera otro).
            </div>
            <textarea rows={8} readOnly value={nuevo.mensaje} />
            <div className="acciones-fila envoltura">
              <a className="btn btn-primario" href={nuevo.whatsapp_url} target="_blank" rel="noreferrer"
                onClick={() => setEnviadoPor('whatsapp')}>Abrir en WhatsApp</a>
              {nuevo.mailto_url && (
                <a className="btn btn-secundario" href={nuevo.mailto_url} onClick={() => setEnviadoPor('email')}>
                  Abrir en el correo
                </a>
              )}
              <button className="btn btn-secundario" onClick={() => copiar(nuevo.mensaje, 'mensaje')}>
                {copiado === 'mensaje' ? 'Copiado ✓' : 'Copiar mensaje'}
              </button>
              <button className="btn btn-secundario" onClick={() => copiar(nuevo.url, 'enlace')}>
                {copiado === 'enlace' ? 'Copiado ✓' : 'Copiar solo el enlace'}
              </button>
            </div>
            {enviadoPor && (
              <div className="alerta-exito">
                ¿Lo enviaste? Regístralo en el historial.{' '}
                <button className="btn btn-chico btn-primario" disabled={registrar.isPending}
                  onClick={() => registrar.mutate(enviadoPor)}>Registrar gestión</button>
              </div>
            )}
          </>
        ) : vigente ? (
          <dl className="datos">
            <dt>Estado</dt>
            <dd>{vigente.bloqueado
              ? <span className="etiqueta etiqueta-castigo">Bloqueado por RUT equivocado</span>
              : <span className="etiqueta etiqueta-pagada">Activo</span>}</dd>
            <dt>Creado</dt>
            <dd>{fechaLegible(vigente.created_at)}{vigente.creado_por && ` por ${vigente.creado_por}`}</dd>
            <dt>Vence</dt><dd>{fechaLegible(vigente.expira_at)}</dd>
            <dt>Abierto</dt>
            <dd>
              {vigente.accesos === 0 ? 'Todavía no lo abre'
                : `${vigente.accesos} ${vigente.accesos === 1 ? 'vez' : 'veces'}, la última el ${fechaHoraLegible(vigente.ultimo_acceso_at!)}`}
            </dd>
          </dl>
        ) : <p>Este deudor todavía no tiene enlace.</p>}

        {error && <div className="alerta-error">{error}</div>}

        <div className="fila">
          <button className="btn btn-primario" disabled={generar.isPending} onClick={() => {
            if (!activo || confirm('El enlace anterior dejará de funcionar. ¿Generar uno nuevo?')) generar.mutate()
          }}>{activo ? 'Generar enlace nuevo' : 'Generar enlace'}</button>
          {activo && (
            <button className="btn btn-secundario" disabled={desactivar.isPending} onClick={() => {
              if (confirm('¿Desactivar el enlace? El deudor ya no podrá abrirlo.')) desactivar.mutate()
            }}>Desactivar</button>
          )}
          <button className="btn btn-secundario" onClick={alCerrar}>Cerrar</button>
        </div>
      </div>
    </div>
  )
}

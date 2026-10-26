import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, mensajeDeError } from '../api/client'
import type { CausaDetalle } from '../api/judicial'
import type { Cobranza, CobranzaDetalle } from '../api/tipos'
import { NOMBRE_DOCUMENTO, Plata, clp, fechaLocal } from './utiles'
import { useConfirmacion } from './ConfirmarGestion'
import {
  procedimientoPorDocumento, useCatalogos, useEquipoJudicial, useTribunales,
} from './usarJudicial'

// Presentar la demanda: una causa (un rol en un tribunal) con una o varias
// cobranzas del mismo deudor y cliente. Al guardar, las cobranzas pasan a
// judicial y queda el primer trámite con su plazo.

export default function NuevaDemanda({ cobranza, alCerrar }: {
  cobranza: CobranzaDetalle; alCerrar: () => void
}) {
  const qc = useQueryClient()
  const navegar = useNavigate()
  const { data: catalogos } = useCatalogos()
  const { data: tribunales } = useTribunales()
  const { data: equipo } = useEquipoJudicial()

  // Otras cobranzas abiertas del mismo deudor con el mismo cliente.
  const { data: hermanas } = useQuery({
    queryKey: ['cobranzas-deudor', cobranza.deudor_id, cobranza.cliente_id],
    queryFn: async () => (await api.get<Cobranza[]>('/cobranzas/', {
      params: { deudor_id: cobranza.deudor_id, cliente_id: cobranza.cliente_id, limit: 100 },
    })).data.filter((c) => ['activa', 'acuerdo_pago'].includes(c.estado) && c.etapa !== 'judicial'),
  })

  const [elegidas, setElegidas] = useState<string[]>([cobranza.id])
  const [procedimiento, setProcedimiento] = useState(procedimientoPorDocumento(cobranza.tipo_documento))
  const [tribunalId, setTribunalId] = useState('')
  const [rol, setRol] = useState('')
  const [fecha, setFecha] = useState(fechaLocal())
  const [abogadoId, setAbogadoId] = useState('')
  const [procuradorId, setProcuradorId] = useState('')
  const [cuantia, setCuantia] = useState('')
  const [observaciones, setObservaciones] = useState('')
  const [error, setError] = useState('')

  const lista = hermanas ?? []
  const suma = lista.filter((c) => elegidas.includes(c.id)).reduce((s, c) => s + Number(c.monto_actual), 0)

  const porCiudad = useMemo(() => {
    const grupos = new Map<string, typeof tribunales>()
    for (const t of tribunales ?? []) {
      const clave = t.ciudad ?? 'Otros'
      grupos.set(clave, [...(grupos.get(clave) ?? []), t])
    }
    return Array.from(grupos.entries())
  }, [tribunales])

  const { pedir, modal } = useConfirmacion()
  function confirmar() {
    const tribunal = tribunales?.find((t) => String(t.id) === tribunalId)?.nombre
    const donde = [rol.trim() ? `rol ${rol.trim()}` : '', tribunal ? `en ${tribunal}` : ''].filter(Boolean).join(' ')
    pedir({
      titulo: `Presentar demanda (${elegidas.length} cobranza${elegidas.length === 1 ? '' : 's'})`,
      gestion: `DEMANDA PRESENTADA: ${catalogos?.procedimientos[procedimiento] ?? procedimiento}${donde ? `, ${donde}` : ''}.`,
      detalle: <p className="suave">Queda en cada cobranza de la demanda. Pasan a judicial y no vuelven atrás.</p>,
      confirmar: 'Sí, presentar demanda', accion: () => guardar.mutateAsync(),
    })
  }

  function alternar(id: string) {
    setElegidas((e) => e.includes(id) ? e.filter((x) => x !== id) : [...e, id])
  }

  const guardar = useMutation({
    mutationFn: async () => (await api.post<CausaDetalle>('/judicial/causas', {
      cobranza_ids: elegidas,
      procedimiento,
      tribunal_id: tribunalId ? Number(tribunalId) : null,
      rol: rol.trim() || null,
      fecha_ingreso: fecha,
      abogado_id: abogadoId || null,
      procurador_id: procuradorId || null,
      cuantia: cuantia ? Number(cuantia) : null,
      observaciones: observaciones.trim() || null,
    })).data,
    onSuccess: (causa) => {
      for (const id of elegidas) {
        qc.invalidateQueries({ queryKey: ['cobranza', id] })
        qc.invalidateQueries({ queryKey: ['ciclo', id] })
        qc.invalidateQueries({ queryKey: ['gestiones', id] })
      }
      qc.invalidateQueries({ queryKey: ['judicial'] })
      navegar(`/judicial/causas/${causa.id}`)
    },
    onError: (e) => setError(mensajeDeError(e)),
  })

  return (
    <div className="modal-fondo" onClick={alCerrar}>
      <div className="modal modal-ancho" onClick={(e) => e.stopPropagation()}>
        <h3>Presentar demanda</h3>
        <p className="suave">
          Las cobranzas elegidas pasan a judicial y no vuelven atrás. Si el deudor tiene más deudas
          con este cliente, pueden ir en la misma demanda (un solo rol).
        </p>

        <div className="subtitulo">Cobranzas en la demanda</div>
        <ul className="lista-elegibles">
          {lista.map((c) => (
            <li key={c.id}>
              <label className="check">
                <input type="checkbox" checked={elegidas.includes(c.id)} onChange={() => alternar(c.id)} />
                <span className="mono negrita">N° {c.numero}</span>
                <span className="suave">
                  {NOMBRE_DOCUMENTO[c.tipo_documento] ?? c.tipo_documento}
                  {c.numero_documento && ` N° ${c.numero_documento}`}
                </span>
                <span className="der"><Plata valor={c.monto_actual} /></span>
              </label>
            </li>
          ))}
        </ul>

        <div className="form-grilla">
          <label>
            Procedimiento
            <select value={procedimiento} onChange={(e) => setProcedimiento(e.target.value)}>
              {Object.entries(catalogos?.procedimientos ?? {}).map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </select>
          </label>
          <label>
            Tribunal
            <select value={tribunalId} onChange={(e) => setTribunalId(e.target.value)}>
              <option value="">Aún no se distribuye</option>
              {porCiudad.map(([ciudad, lista]) => (
                <optgroup key={ciudad} label={ciudad}>
                  {lista?.map((t) => <option key={t.id} value={t.id}>{t.nombre}</option>)}
                </optgroup>
              ))}
            </select>
          </label>
          <label>
            Rol
            <input value={rol} onChange={(e) => setRol(e.target.value)} placeholder="C-1234-2026 (si ya lo tiene)" />
          </label>
          <label>
            Fecha de presentación
            <input type="date" value={fecha} max={fechaLocal()} onChange={(e) => setFecha(e.target.value)} />
          </label>
          <label>
            Abogado
            <select value={abogadoId} onChange={(e) => setAbogadoId(e.target.value)}>
              <option value="">Sin asignar</option>
              {equipo?.map((u) => <option key={u.id} value={u.id}>{u.nombre}</option>)}
            </select>
          </label>
          <label>
            Procurador
            <select value={procuradorId} onChange={(e) => setProcuradorId(e.target.value)}>
              <option value="">Sin asignar</option>
              {equipo?.map((u) => <option key={u.id} value={u.id}>{u.nombre}</option>)}
            </select>
          </label>
          <label>
            Cuantía
            <input type="number" min={0} value={cuantia} onChange={(e) => setCuantia(e.target.value)}
              placeholder={`${clp(suma)} (suma de los saldos)`} />
          </label>
          <label className="ancho-completo">
            Observaciones
            <textarea rows={2} value={observaciones} onChange={(e) => setObservaciones(e.target.value)} />
          </label>
        </div>

        {error && <div className="alerta-error">{error}</div>}
        <div className="acciones-fila">
          <button className="btn btn-primario" disabled={guardar.isPending || elegidas.length === 0}
            onClick={confirmar}>
            {guardar.isPending ? 'Guardando…' : `Presentar demanda (${elegidas.length} cobranza${elegidas.length === 1 ? '' : 's'})`}
          </button>
          <button className="btn btn-secundario" onClick={alCerrar}>Cancelar</button>
        </div>
      </div>
      {modal}
    </div>
  )
}

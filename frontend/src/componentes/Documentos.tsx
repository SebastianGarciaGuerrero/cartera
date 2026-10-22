import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, mensajeDeError } from '../api/client'
import type { TipoDocumento } from '../api/tipos'
import { NOMBRE_DOCUMENTO, Plata, fechaLegible } from './utiles'
import { diasHasta } from './usarJudicial'

// Documentos que respaldan la cobranza (cheques, facturas, letras,
// pagarés…), cada uno con su vencimiento, banco, protesto y prescripción.

export interface Documento {
  id: string
  cobranza_id: string
  tipo: TipoDocumento
  numero: string | null
  fecha_emision: string | null
  fecha_vencimiento: string | null
  monto: string | null
  banco: string | null
  plaza: string | null
  causal_protesto: string | null
  fecha_protesto: string | null
  observaciones: string | null
  activo: boolean
  fecha_prescripcion: string | null
}

const VACIO = {
  tipo: 'cheque' as TipoDocumento, numero: '', fecha_emision: '', fecha_vencimiento: '', monto: '',
  banco: '', plaza: '', causal_protesto: '', fecha_protesto: '',
}

export default function Documentos({ cobranzaId }: { cobranzaId: string }) {
  const qc = useQueryClient()
  const [nuevo, setNuevo] = useState(false)
  const [d, setD] = useState(VACIO)
  const [error, setError] = useState('')
  const { data: docs } = useQuery({
    queryKey: ['documentos', cobranzaId],
    queryFn: async () => (await api.get<Documento[]>(`/cobranzas/${cobranzaId}/documentos`)).data,
  })
  const refrescar = () => {
    qc.invalidateQueries({ queryKey: ['documentos', cobranzaId] })
    qc.invalidateQueries({ queryKey: ['ciclo', cobranzaId] })
  }
  const agregar = useMutation({
    mutationFn: () => api.post(`/cobranzas/${cobranzaId}/documentos`, Object.fromEntries(
      Object.entries(d).map(([k, v]) => [k, v === '' ? null : k === 'monto' ? Number(v) : v]))),
    onSuccess: () => { setNuevo(false); setD(VACIO); setError(''); refrescar() },
    onError: (e) => setError(mensajeDeError(e)),
  })
  const quitar = useMutation({
    mutationFn: (id: string) => api.put(`/cobranzas/documentos/${id}`, { activo: false }),
    onSuccess: refrescar,
  })

  const total = (docs ?? []).reduce((s, x) => s + Number(x.monto ?? 0), 0)
  const campo = (k: keyof typeof VACIO) => ({
    value: d[k], onChange: (e: { target: { value: string } }) => setD({ ...d, [k]: e.target.value }),
  })

  return (
    <section className="tarjeta separado">
      <div className="tarjeta-cabecera">
        <h2>Documentos ({docs?.length ?? 0}) · <Plata valor={total} /></h2>
        {!nuevo && <button className="btn btn-chico btn-secundario" onClick={() => setNuevo(true)}>Agregar documento</button>}
      </div>
      {nuevo && (
        <form className="form-grilla" onSubmit={(e) => { e.preventDefault(); agregar.mutate() }}>
          <label>Tipo
            <select {...campo('tipo')}>
              {Object.entries(NOMBRE_DOCUMENTO).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
          <label>N° documento<input {...campo('numero')} /></label>
          <label>Monto<input type="number" min={0} {...campo('monto')} /></label>
          <label>Vencimiento<input type="date" {...campo('fecha_vencimiento')} /></label>
          <label>Banco<input {...campo('banco')} /></label>
          <label>Plaza<input {...campo('plaza')} /></label>
          {(d.tipo === 'cheque' || d.tipo === 'letra' || d.tipo === 'pagare') && (
            <>
              <label>Fecha de protesto<input type="date" {...campo('fecha_protesto')} /></label>
              <label>Causal del protesto<input {...campo('causal_protesto')} placeholder="Falta de fondos, cuenta cerrada…" /></label>
            </>
          )}
          {error && <div className="alerta-error ancho-completo">{error}</div>}
          <div className="acciones-fila ancho-completo">
            <button className="btn btn-primario" disabled={agregar.isPending}>Guardar</button>
            <button type="button" className="btn btn-secundario" onClick={() => setNuevo(false)}>Cancelar</button>
          </div>
        </form>
      )}
      {docs && docs.length > 0 && (
        <div className="tabla-desplazable">
          <table className="tabla">
            <thead>
              <tr><th>Documento</th><th>Vence</th><th className="der">Monto</th><th>Banco / plaza</th><th>Protesto</th><th>Prescribe</th><th></th></tr>
            </thead>
            <tbody>
              {docs.map((x) => {
                const dias = diasHasta(x.fecha_prescripcion)
                return (
                  <tr key={x.id}>
                    <td>{NOMBRE_DOCUMENTO[x.tipo] ?? x.tipo}{x.numero && <span className="mono suave"> N° {x.numero}</span>}</td>
                    <td>{fechaLegible(x.fecha_vencimiento)}</td>
                    <td className="der">{x.monto ? <Plata valor={x.monto} /> : '—'}</td>
                    <td>{[x.banco, x.plaza].filter(Boolean).join(' · ') || '—'}</td>
                    <td>{x.fecha_protesto ? <>{fechaLegible(x.fecha_protesto)}{x.causal_protesto && <div className="suave">{x.causal_protesto}</div>}</> : '—'}</td>
                    <td className={dias != null && dias <= 90 ? 'texto-rojo negrita' : ''}>
                      {x.fecha_prescripcion ? fechaLegible(x.fecha_prescripcion) : '—'}
                    </td>
                    <td>
                      {docs.length > 1 && (
                        <button className="btn-texto" disabled={quitar.isPending}
                          onClick={() => { if (window.confirm('¿Quitar este documento de la cobranza?')) quitar.mutate(x.id) }}>
                          Quitar
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="nota">La prescripción es referencial (cheque: un año desde el protesto); confírmela con el abogado.</p>
    </section>
  )
}

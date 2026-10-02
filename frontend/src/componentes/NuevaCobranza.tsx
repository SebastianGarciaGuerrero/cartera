import { useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, mensajeDeError } from '../api/client'
import type { Cliente, Filial, Deudor, Cobranza, DatosExtra } from '../api/tipos'
import { useAuth } from '../auth'
import { FormularioCamposExtra, useCampos } from './CamposExtra'
import { NOMBRE_DOCUMENTO } from './utiles'

// Alta de cobranza: cliente + filial + deudor (buscándolo por RUT/nombre)
// + monto + documento que identifica la deuda (pagaré, factura...).
// El N° de cobranza lo asigna PostgreSQL; el saldo parte igual a la deuda.
// Con enPagina=true el formulario vive en su propia página (siempre abierto).

const TIPOS_DOCUMENTO = Object.entries(NOMBRE_DOCUMENTO)

export default function NuevaCobranza({ enPagina = false }: { enPagina?: boolean }) {
  const qc = useQueryClient()
  const navegar = useNavigate()
  const { etiqueta } = useAuth()
  const [abierto, setAbierto] = useState(enPagina)

  const [clienteId, setClienteId] = useState('')
  const [filialId, setFilialId] = useState('')
  const [idExterno, setIdExterno] = useState('')
  const [monto, setMonto] = useState('')
  const [tipoDocumento, setTipoDocumento] = useState('pagare')
  const [numeroDocumento, setNumeroDocumento] = useState('')
  const [vencimiento, setVencimiento] = useState('')
  const [datosExtra, setDatosExtra] = useState<DatosExtra>({})
  const [observaciones, setObservaciones] = useState('')
  const [error, setError] = useState('')

  // Selección de deudor con buscador.
  const [busquedaDeudor, setBusquedaDeudor] = useState('')
  const [deudor, setDeudor] = useState<Deudor | null>(null)

  const { data: clientes } = useQuery({
    queryKey: ['clientes'],
    queryFn: async () => (await api.get<Cliente[]>('/clientes/')).data,
  })

  const { data: campos } = useCampos('cobranza', clienteId || null)

  const { data: filiales } = useQuery({
    queryKey: ['filiales', clienteId],
    enabled: clienteId !== '',
    queryFn: async () =>
      (await api.get<Filial[]>('/filiales/', { params: { cliente_id: clienteId } })).data,
  })

  const { data: candidatos } = useQuery({
    queryKey: ['buscar-deudor', busquedaDeudor],
    enabled: busquedaDeudor.trim().length >= 2 && deudor === null,
    queryFn: async () =>
      (await api.get<Deudor[]>('/deudores/buscar', {
        params: { q: busquedaDeudor.trim(), limit: 6 },
      })).data,
  })

  const crear = useMutation({
    mutationFn: async () => {
      const { data } = await api.post<Cobranza>('/cobranzas/', {
        cliente_id: clienteId,
        filial_id: filialId ? Number(filialId) : null,
        deudor_id: deudor!.id,
        id_externo: idExterno || null,
        monto_original: monto,
        tipo_documento: tipoDocumento,
        numero_documento: numeroDocumento || null,
        fecha_vencimiento_documento: vencimiento || null,
        datos_extra: Object.fromEntries(
          Object.entries(datosExtra).filter(([, v]) => v !== '' && v !== undefined),
        ),
        observaciones: observaciones || null,
      })
      return data
    },
    onSuccess: (nueva) => {
      qc.invalidateQueries({ queryKey: ['cobranzas'] })
      navegar(`/cobranzas/${nueva.id}`)  // directo a la ficha recién creada
    },
    onError: (err) => setError(mensajeDeError(err)),
  })

  if (!abierto) {
    return (
      <button className="btn btn-primario" onClick={() => setAbierto(true)}>
        + Nueva cobranza
      </button>
    )
  }

  function alEnviar(e: FormEvent) {
    e.preventDefault()
    setError('')
    if (!deudor) {
      setError('Selecciona el deudor (búscalo por RUT o nombre).')
      return
    }
    crear.mutate()
  }

  return (
    <form className="form-finanzas form-alta" onSubmit={alEnviar}>
      <h3>Nueva cobranza</h3>

      <div className="fila">
        <label>
          {etiqueta('cliente', 'Cliente')} *
          <select value={clienteId} required
            onChange={(e) => { setClienteId(e.target.value); setFilialId('') }}>
            <option value="">Seleccionar…</option>
            {clientes?.map((c) => (
              <option key={c.id} value={c.id}>{c.nombre_fantasia ?? c.razon_social}</option>
            ))}
          </select>
        </label>
        <label>
          {etiqueta('filial', 'Filial')}
          <select value={filialId} onChange={(e) => setFilialId(e.target.value)}
            disabled={!clienteId}>
            <option value="">—</option>
            {filiales?.map((f) => (
              <option key={f.id} value={f.id}>{f.nombre}</option>
            ))}
          </select>
        </label>
      </div>

      <label>
        Deudor * <span className="suave">(si no existe, créalo primero en la sección Deudores)</span>
        {deudor ? (
          <div className="deudor-elegido">
            <span><strong>{deudor.nombre}</strong> <span className="mono suave">{deudor.rut}</span></span>
            <button type="button" className="btn btn-chico btn-secundario"
              onClick={() => { setDeudor(null); setBusquedaDeudor('') }}>
              Cambiar
            </button>
          </div>
        ) : (
          <>
            <input
              value={busquedaDeudor}
              onChange={(e) => setBusquedaDeudor(e.target.value)}
              placeholder="Buscar por RUT o nombre…"
            />
            {candidatos && candidatos.length > 0 && (
              <ul className="sugerencias">
                {candidatos.map((d) => (
                  <li key={d.id}>
                    <button type="button" onClick={() => setDeudor(d)}>
                      {d.nombre} <span className="mono suave">{d.rut}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {candidatos && candidatos.length === 0 && (
              <div className="suave">Sin resultados para "{busquedaDeudor}".</div>
            )}
          </>
        )}
      </label>

      <div className="fila">
        <label>
          Monto de la deuda *
          <input type="number" min="1" value={monto}
            onChange={(e) => setMonto(e.target.value)} required />
        </label>
        <label>
          {etiqueta('id_externo', 'ID cliente')}
          <input value={idExterno} onChange={(e) => setIdExterno(e.target.value)}
            placeholder="N° interno del cliente (SAP, HIS…)" />
        </label>
      </div>

      <div className="fila">
        <label>
          Tipo de documento
          <select value={tipoDocumento} onChange={(e) => setTipoDocumento(e.target.value)}>
            {TIPOS_DOCUMENTO.map(([valor, nombre]) => (
              <option key={valor} value={valor}>{nombre}</option>
            ))}
          </select>
        </label>
        <label>
          N° de documento
          <input value={numeroDocumento} onChange={(e) => setNumeroDocumento(e.target.value)}
            placeholder="N° de pagaré, factura…" />
        </label>
        <label>
          Vencimiento del documento
          <input type="date" value={vencimiento} onChange={(e) => setVencimiento(e.target.value)} />
        </label>
      </div>

      <FormularioCamposExtra campos={campos} valores={datosExtra} onChange={setDatosExtra} />

      <label>
        Observaciones
        <textarea rows={2} value={observaciones} onChange={(e) => setObservaciones(e.target.value)} />
      </label>

      <p className="nota">
        El N° de cobranza lo asigna el sistema automáticamente y no se puede cambiar.
      </p>
      {error && <div className="alerta-error">{error}</div>}
      <div className="fila">
        <button className="btn btn-primario" disabled={crear.isPending}>
          {crear.isPending ? 'Creando…' : 'Crear cobranza'}
        </button>
        <button
          type="button"
          className="btn btn-secundario"
          onClick={() => (enPagina ? navegar('/cobranzas') : setAbierto(false))}
        >
          Cancelar
        </button>
      </div>
    </form>
  )
}

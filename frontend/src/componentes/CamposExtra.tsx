import { Fragment } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { CampoPersonalizado, DatosExtra } from '../api/tipos'

// Campos personalizados de la organización: formulario (para altas y
// ediciones) y vista de solo lectura (para fichas).

export function useCampos(entidad: 'cobranza' | 'deudor', clienteId?: string | null) {
  return useQuery({
    queryKey: ['campos', entidad, clienteId ?? null],
    queryFn: async () =>
      (await api.get<CampoPersonalizado[]>('/campos', {
        params: { entidad, ...(clienteId ? { cliente_id: clienteId } : {}) },
      })).data,
    staleTime: 5 * 60 * 1000,
  })
}

export function FormularioCamposExtra({
  campos, valores, onChange,
}: {
  campos: CampoPersonalizado[] | undefined
  valores: DatosExtra
  onChange: (valores: DatosExtra) => void
}) {
  if (!campos || campos.length === 0) return null
  const fijar = (clave: string, valor: string | boolean) => onChange({ ...valores, [clave]: valor })

  return (
    <div className="fila" style={{ flexWrap: 'wrap' }}>
      {campos.map((c) => {
        const valor = valores[c.clave]
        const titulo = `${c.etiqueta}${c.obligatorio ? ' *' : ''}`
        if (c.tipo === 'si_no') {
          return (
            <label key={c.id} className="check">
              <input type="checkbox" checked={valor === true}
                onChange={(e) => fijar(c.clave, e.target.checked)} />
              {titulo}
            </label>
          )
        }
        if (c.tipo === 'seleccion') {
          return (
            <label key={c.id}>{titulo}
              <select value={(valor as string) ?? ''} required={c.obligatorio}
                onChange={(e) => fijar(c.clave, e.target.value)}>
                <option value="">—</option>
                {c.opciones.map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            </label>
          )
        }
        return (
          <label key={c.id}>{titulo}
            <input
              type={c.tipo === 'fecha' ? 'date' : c.tipo === 'texto' ? 'text' : 'number'}
              step={c.tipo === 'monto' ? '1' : 'any'}
              value={(valor as string) ?? ''}
              required={c.obligatorio}
              onChange={(e) => fijar(c.clave, e.target.value)}
            />
          </label>
        )
      })}
    </div>
  )
}

export function VistaCamposExtra({
  campos, valores,
}: {
  campos: CampoPersonalizado[] | undefined
  valores: DatosExtra | undefined
}) {
  if (!campos || !valores) return null
  const conValor = campos.filter((c) => valores[c.clave] !== undefined && valores[c.clave] !== '')
  if (conValor.length === 0) return null
  return (
    <>
      {conValor.map((c) => {
        const v = valores[c.clave]
        const texto = typeof v === 'boolean' ? (v ? 'Sí' : 'No')
          : c.tipo === 'monto' ? `$${Number(v).toLocaleString('es-CL')}`
          : c.tipo === 'fecha' ? new Date(`${v}T12:00:00`).toLocaleDateString('es-CL')
          : String(v)
        return (
          <Fragment key={c.id}>
            <dt>{c.etiqueta}</dt>
            <dd>{texto}</dd>
          </Fragment>
        )
      })}
    </>
  )
}

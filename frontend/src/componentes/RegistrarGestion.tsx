import { useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, mensajeDeError } from '../api/client'
import { refrescarCaso } from '../api/refrescar'
import type { Acuerdo, AcuerdoDetalle, CobranzaDetalle, TipoGestion } from '../api/tipos'
import { FormPago } from './Finanzas'
import { Plata, clp, enDias, fechaLegible, fechaLocal, sumarMeses } from './utiles'

// Registrar gestión en un paso: qué pasó y cuál fue el resultado.
//   - Gestión: tipo + comentario (+ próximo contacto, opcional).
//   - Promesa: fecha y monto prometidos → sale en la agenda ese día.
//   - Acuerdo: montos y cuotas (se reparten solas y se pueden escribir a mano)
//     → queda el acuerdo y UNA gestión con sus términos; las cuotas avisan a
//     quien lo registró.
//   - Pago: la próxima cuota viene elegida; el pago deja su gestión.
// Todo lo demás es opcional: quien prefiera anotar a mano, usa los
// recordatorios de la agenda.

export type ResultadoGestion = 'gestion' | 'promesa' | 'acuerdo' | 'pago'

const RESULTADOS: { valor: ResultadoGestion; nombre: string; ayuda: string }[] = [
  { valor: 'gestion', nombre: 'Gestión', ayuda: 'Llamada, mensaje, visita…' },
  { valor: 'promesa', nombre: 'Promesa de pago', ayuda: 'Pagará en una fecha' },
  { valor: 'acuerdo', nombre: 'Acuerdo de pago', ayuda: 'Pago en cuotas' },
  { valor: 'pago', nombre: 'Pago / abono', ayuda: 'Ya pagó' },
]

// Tipos que el sistema registra solo (desde un acuerdo, un pago, etc.).
const TIPOS_AUTOMATICOS = new Set(['automatica', 'ingreso', 'acuerdo', 'abono', 'pagado', 'promesa_pago'])

interface CuotaEditable { fecha: string; monto: string }

/** Reparte lo que queda después del pie en N cuotas mensuales; el resto de pesos va en la última. */
function repartir(total: number, pie: number, n: number, primera: string): CuotaEditable[] {
  const resto = Math.round(total - pie)
  if (!(n >= 1 && n <= 120) || !primera || !(resto > 0)) return []
  const base = Math.floor(resto / n)
  return Array.from({ length: n }, (_, i) => ({
    fecha: sumarMeses(primera, i),
    monto: String(i === n - 1 ? resto - base * (n - 1) : base),
  }))
}

function finDeMes(): string {
  const d = new Date()
  return fechaLocal(new Date(d.getFullYear(), d.getMonth() + 1, 0))
}

const ATAJOS_FECHA: [string, () => string][] = [
  ['Mañana', () => enDias(1)], ['En 3 días', () => enDias(3)],
  ['En una semana', () => enDias(7)], ['Fin de mes', finDeMes],
]

export default function RegistrarGestion({ cobranza, resultado, setResultado }: {
  cobranza: CobranzaDetalle
  resultado: ResultadoGestion
  setResultado: (r: ResultadoGestion) => void
}) {
  const qc = useQueryClient()
  const [tipoId, setTipoId] = useState<number | null>(null)
  const [descripcion, setDescripcion] = useState('')
  const [proximo, setProximo] = useState('')
  const [promesaFecha, setPromesaFecha] = useState('')
  const [promesaMonto, setPromesaMonto] = useState('')
  const [error, setError] = useState('')
  const [listo, setListo] = useState('')

  // Acuerdo
  const [total, setTotal] = useState(String(Math.round(Number(cobranza.monto_actual))))
  const [pie, setPie] = useState('0')
  const [nCuotas, setNCuotas] = useState('6')
  const [primera, setPrimera] = useState(() => sumarMeses(fechaLocal(), 1))
  const [cuotasEditadas, setCuotasEditadas] = useState<CuotaEditable[] | null>(null)
  const cuotasAuto = useMemo(() => repartir(Number(total), Number(pie) || 0, Number(nCuotas), primera),
    [total, pie, nCuotas, primera])
  const cuotas = cuotasEditadas ?? cuotasAuto
  const sumaCuotas = cuotas.reduce((s, c) => s + (Number(c.monto) || 0), 0)
  const enCuotas = Math.round(Number(total) - (Number(pie) || 0))
  const cuadra = cuotas.length > 0 && Math.round(sumaCuotas) === enCuotas
    && cuotas.every((c) => c.fecha && Number(c.monto) > 0)

  // Pago
  const [cuotaElegida, setCuotaElegida] = useState('')

  const { data: tipos } = useQuery({
    queryKey: ['tipos-gestion'],
    queryFn: async () => (await api.get<TipoGestion[]>('/gestiones/tipos')).data,
  })
  const { data: acuerdos } = useQuery({
    queryKey: ['acuerdos', cobranza.id],
    queryFn: async () => (await api.get<Acuerdo[]>('/acuerdos/', { params: { cobranza_id: cobranza.id } })).data,
  })
  const vigente = acuerdos?.find((a) => a.estado === 'vigente')
  const { data: detalle } = useQuery({
    queryKey: ['acuerdo', vigente?.id],
    enabled: vigente !== undefined,
    queryFn: async () => (await api.get<AcuerdoDetalle>(`/acuerdos/${vigente!.id}`)).data,
  })
  const pendientes = vigente && detalle
    ? detalle.cuotas.filter((c) => c.estado !== 'pagada').sort((a, b) => a.numero_cuota - b.numero_cuota) : []
  const idCuota = cuotaElegida || pendientes[0]?.id || 'libre'
  const cuotaPago = pendientes.find((c) => c.id === idCuota) ?? null

  const opcionesTipo = (tipos ?? []).filter((t) => t.activo && !TIPOS_AUTOMATICOS.has(t.codigo ?? '')
    && (resultado === 'gestion' || (t.categoria === 'contacto' && t.codigo !== 'no_contesta')))

  function terminar(texto: string) {
    setDescripcion(''); setProximo(''); setPromesaFecha(''); setPromesaMonto('')
    setTipoId(null); setCuotasEditadas(null); setCuotaElegida(''); setError('')
    setListo(texto)
    setResultado('gestion')
    refrescarCaso(qc, cobranza.id)
    window.setTimeout(() => setListo(''), 5000)
  }

  const guardar = useMutation({
    mutationFn: async () => {
      const cuerpo: Record<string, unknown> = {
        cobranza_id: cobranza.id, resultado, tipo_id: tipoId, descripcion: descripcion.trim() || null,
      }
      if (resultado === 'gestion') cuerpo.fecha_proximo_contacto = proximo || null
      if (resultado === 'promesa') cuerpo.promesa = { fecha: promesaFecha, monto: Number(promesaMonto) || null }
      if (resultado === 'acuerdo') {
        cuerpo.acuerdo = {
          monto_total_acordado: Number(total), pie: Number(pie) || 0, numero_cuotas: cuotas.length,
          fecha_primera_cuota: cuotas[0].fecha,
          cuotas: cuotas.map((c) => ({ fecha_vencimiento: c.fecha, monto: Number(c.monto) })),
        }
      }
      await api.post('/gestiones/completa', cuerpo)
    },
    onSuccess: () => terminar(
      resultado === 'promesa' ? `Promesa registrada: te aparecerá en la agenda el ${fechaLegible(promesaFecha)}.`
        : resultado === 'acuerdo' ? 'Acuerdo registrado. Cada cuota te aparecerá en la agenda y en los avisos (el día antes y el día que vence).'
          : proximo ? `Gestión registrada. Próximo contacto el ${fechaLegible(proximo)}.` : 'Gestión registrada.',
    ),
    onError: (e) => setError(mensajeDeError(e)),
  })

  function editarCuota(i: number, campo: keyof CuotaEditable, valor: string) {
    setCuotasEditadas(cuotas.map((c, j) => (j === i ? { ...c, [campo]: valor } : c)))
  }

  const textoBoton = {
    gestion: 'Registrar gestión', promesa: 'Registrar promesa', acuerdo: 'Registrar acuerdo', pago: '',
  }[resultado]

  return (
    <div id="registrar-gestion">
      <h2>Registrar gestión</h2>
      <div className="resultados">
        {RESULTADOS.map((r) => (
          <button key={r.valor} type="button" className={`resultado-opcion ${resultado === r.valor ? 'elegida' : ''}`}
            aria-pressed={resultado === r.valor} onClick={() => { setResultado(r.valor); setError('') }}>
            <strong>{r.nombre}</strong>
            <span>{r.ayuda}</span>
          </button>
        ))}
      </div>
      {listo && <div className="alerta-exito">{listo}</div>}

      {resultado === 'pago' ? (
        <>
          {pendientes.length > 0 && (
            <div className="opciones-cuota">
              {pendientes.map((c) => (
                <label key={c.id} className={`opcion ${idCuota === c.id ? 'elegida' : ''}`}>
                  <input type="radio" name="cuota-gestion" checked={idCuota === c.id} onChange={() => setCuotaElegida(c.id)} />
                  <span>Cuota {c.numero_cuota}/{vigente?.numero_cuotas}</span>
                  <span className={c.fecha_vencimiento < fechaLocal() ? 'texto-rojo' : 'suave'}>
                    vence {fechaLegible(c.fecha_vencimiento)}
                  </span>
                  <strong><Plata valor={Number(c.monto) - Number(c.monto_pagado)} /></strong>
                </label>
              ))}
              <label className={`opcion ${idCuota === 'libre' ? 'elegida' : ''}`}>
                <input type="radio" name="cuota-gestion" checked={idCuota === 'libre'} onChange={() => setCuotaElegida('libre')} />
                <span>Abono libre</span>
                <span className="suave">sin imputar a una cuota</span>
              </label>
            </div>
          )}
          <FormPago key={idCuota} cobranzaId={cobranza.id} modalidad={cobranza.tipo} cuota={cuotaPago}
            alTerminar={(p) => terminar(`Pago de ${clp(p.monto)} registrado${p.cuota ? ` (cuota ${p.cuota})` : ''}.`)}
            alCancelar={() => setResultado('gestion')} />
        </>
      ) : (
        <form className="form-gestion" onSubmit={(e: FormEvent) => { e.preventDefault(); setError(''); guardar.mutate() }}>
          <div>
            <span className="etiqueta-campo">{resultado === 'gestion' ? 'Tipo' : 'Canal (opcional)'}</span>
            <div className="chips">
              {opcionesTipo.map((t) => (
                <button key={t.id} type="button" className={`chip ${tipoId === t.id ? 'elegido' : ''}`}
                  aria-pressed={tipoId === t.id} onClick={() => setTipoId(tipoId === t.id ? null : t.id)}>
                  {t.nombre}
                </button>
              ))}
            </div>
          </div>

          {resultado === 'promesa' && (
            <div className="fila">
              <label>
                Pagará el *
                <input type="date" value={promesaFecha} min={fechaLocal()} required
                  onChange={(e) => setPromesaFecha(e.target.value)} />
              </label>
              <label>
                Monto prometido
                <input type="number" min="1" value={promesaMonto} placeholder="opcional"
                  onChange={(e) => setPromesaMonto(e.target.value)} />
              </label>
              <div className="chips atajos">
                {ATAJOS_FECHA.map(([nombre, fecha]) => (
                  <button key={nombre} type="button" className="chip" onClick={() => setPromesaFecha(fecha())}>{nombre}</button>
                ))}
              </div>
            </div>
          )}

          {resultado === 'acuerdo' && (vigente ? (
            <div className="alerta-error">
              Esta cobranza ya tiene un acuerdo vigente. Para renegociar, márcalo como renegociado en
              "Acuerdo de pago y pagos" y vuelve a registrar el nuevo.
            </div>
          ) : (
            <div className="acuerdo-manual">
              <div className="fila">
                <label>Monto total *<input type="number" min="1" value={total} required
                  onChange={(e) => { setTotal(e.target.value); setCuotasEditadas(null) }} /></label>
                <label>Pie<input type="number" min="0" value={pie}
                  onChange={(e) => { setPie(e.target.value); setCuotasEditadas(null) }} /></label>
                <label>N° de cuotas *<input type="number" min="1" max="120" value={nCuotas} required
                  onChange={(e) => { setNCuotas(e.target.value); setCuotasEditadas(null) }} /></label>
                <label>Primera cuota *<input type="date" value={primera} required
                  onChange={(e) => { setPrimera(e.target.value); setCuotasEditadas(null) }} /></label>
              </div>
              {cuotas.length > 0 && (
                <>
                  <div className="tabla-desplazable cuotas-editables">
                    <table className="tabla">
                      <thead><tr><th>Cuota</th><th>Vence</th><th className="der">Monto</th></tr></thead>
                      <tbody>
                        {cuotas.map((c, i) => (
                          <tr key={i}>
                            <td className="mono">{i + 1}/{cuotas.length}</td>
                            <td><input type="date" value={c.fecha} aria-label={`Vencimiento cuota ${i + 1}`}
                              onChange={(e) => editarCuota(i, 'fecha', e.target.value)} /></td>
                            <td><input type="number" min="1" value={c.monto} className="der" aria-label={`Monto cuota ${i + 1}`}
                              onChange={(e) => editarCuota(i, 'monto', e.target.value)} /></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <div className="suma-cuotas">
                    <span className={cuadra ? 'suave' : 'texto-rojo negrita'}>
                      Las cuotas suman {clp(sumaCuotas)} de {clp(enCuotas)}
                      {Number(pie) > 0 && ` (más el pie de ${clp(Number(pie))})`}
                    </span>
                    {cuotasEditadas && (
                      <button type="button" className="btn btn-chico btn-secundario" onClick={() => setCuotasEditadas(null)}>
                        Repartir en partes iguales
                      </button>
                    )}
                  </div>
                  <p className="nota">Puedes cambiar la fecha o el monto de cualquier cuota.</p>
                </>
              )}
            </div>
          ))}

          <textarea
            rows={3} value={descripcion} onChange={(e) => setDescripcion(e.target.value)} required={resultado === 'gestion'}
            placeholder={resultado === 'gestion' ? '¿Qué pasó? Ej.: llamada a don Pedro, se compromete a pagar el día 5…'
              : 'Comentario (opcional): queda en la misma gestión'} />

          {resultado === 'gestion' && (
            <div className="fila proximo">
              <label>
                Próximo contacto (opcional)
                <input type="date" value={proximo} min={fechaLocal()} onChange={(e) => setProximo(e.target.value)} />
              </label>
              <div className="chips atajos">
                {ATAJOS_FECHA.slice(0, 3).map(([nombre, fecha]) => (
                  <button key={nombre} type="button" className="chip" onClick={() => setProximo(fecha())}>{nombre}</button>
                ))}
                {proximo && <button type="button" className="chip" onClick={() => setProximo('')}>Sin fecha</button>}
              </div>
            </div>
          )}

          {error && <div className="alerta-error">{error}</div>}
          <button className="btn btn-primario"
            disabled={guardar.isPending || (resultado === 'acuerdo' && (Boolean(vigente) || !cuadra))}>
            {guardar.isPending ? 'Guardando…' : textoBoton}
          </button>
          <p className="nota">
            {resultado === 'acuerdo'
              ? 'Se guarda el acuerdo y una sola gestión con sus términos y tu comentario.'
              : 'Las gestiones no se pueden editar ni borrar después.'}
            {resultado === 'gestion' && ' El próximo contacto aparece solo en tu agenda.'}
          </p>
        </form>
      )}
    </div>
  )
}

import { useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, mensajeDeError } from '../api/client'
import { refrescarCaso } from '../api/refrescar'
import type { Acuerdo, AcuerdoDetalle, CobranzaDetalle, PlanAcuerdo, TipoGestion } from '../api/tipos'
import { FormPago } from './Finanzas'
import { Plata, clp, enDias, fechaLegible, fechaLocal, nombreCuota, sumarMeses } from './utiles'
import { useAuth } from '../auth'
import AcuerdoCalculado from './AcuerdoCalculado'
import type { CuerpoAcuerdo } from './AcuerdoCalculado'
import ConfirmarGestion from './ConfirmarGestion'

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
// Los que deja el sistema solo (al registrar el acuerdo, el pago, la demanda o un cambio): no se eligen a mano.
const TIPOS_AUTOMATICOS = new Set(['automatica', 'ingreso', 'acuerdo', 'abono', 'pagado', 'promesa_pago', 'demanda',
  'gasto', 'tramite', 'embargo', 'etapa', 'cambio_datos'])

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

function proximoViernes(): string {
  const d = new Date()
  const faltan = ((5 - d.getDay() + 7) % 7) || 7
  d.setDate(d.getDate() + faltan)
  return fechaLocal(d)
}

function finDeMes(): string {
  const d = new Date()
  return fechaLocal(new Date(d.getFullYear(), d.getMonth() + 1, 0))
}

const ATAJOS_FECHA: [string, () => string][] = [
  ['Mañana', () => enDias(1)], ['En 3 días', () => enDias(3)],
  ['Próximo viernes', proximoViernes], ['En una semana', () => enDias(7)], ['Fin de mes', finDeMes],
]

export default function RegistrarGestion({ cobranza, resultado, setResultado }: {
  cobranza: CobranzaDetalle
  resultado: ResultadoGestion
  setResultado: (r: ResultadoGestion) => void
}) {
  const qc = useQueryClient()
  const { tiene } = useAuth()
  const conCalculadora = tiene('calculadora_369')
  const [modoAcuerdo, setModoAcuerdo] = useState<'calculado' | 'manual'>(conCalculadora ? 'calculado' : 'manual')
  const [cuerpoCalculado, setCuerpoCalculado] = useState<CuerpoAcuerdo | null>(null)
  const [planCalculado, setPlanCalculado] = useState<PlanAcuerdo | null>(null)
  const [confirmando, setConfirmando] = useState(false)
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
  const [fechaPie, setFechaPie] = useState(fechaLocal())
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
      if (resultado === 'acuerdo' && modoAcuerdo === 'calculado' && cuerpoCalculado) {
        // Mismo cálculo de la calculadora 3-6-9; deja el acuerdo y su gestión.
        const canal = tipos?.find((t) => t.id === tipoId)?.nombre
        const observaciones = [canal ? `Vía: ${canal}.` : '', descripcion.trim()].filter(Boolean).join(' ')
        await api.post('/calculadora/acuerdo/crear', { ...cuerpoCalculado, cobranza_id: cobranza.id, observaciones: observaciones || null })
        return
      }
      if (resultado === 'acuerdo') {
        cuerpo.acuerdo = {
          monto_total_acordado: Number(total), pie: Number(pie) || 0, numero_cuotas: cuotas.length,
          fecha_pie: Number(pie) > 0 ? fechaPie : null,
          fecha_primera_cuota: cuotas[0].fecha,
          cuotas: cuotas.map((c) => ({ fecha_vencimiento: c.fecha, monto: Number(c.monto) })),
        }
      }
      await api.post('/gestiones/completa', cuerpo)
    },
    onSuccess: () => { setConfirmando(false); terminar(
      resultado === 'promesa' ? `Promesa registrada: te aparecerá en la agenda el ${fechaLegible(promesaFecha)}.`
        : resultado === 'acuerdo' ? 'Acuerdo registrado. El pie y cada cuota te aparecerán en la agenda y en los avisos (el día antes y el día que vence).'
          : proximo ? `Gestión registrada. Próximo contacto el ${fechaLegible(proximo)}.` : 'Gestión registrada.',
    ) },
    onError: (e) => setError(mensajeDeError(e)),
  })

  // El acuerdo se confirma antes de guardarlo, mostrando la gestión que dejará.
  function textoAcuerdo(): string {
    const canal = tipos?.find((t) => t.id === tipoId)?.nombre
    const extras = [canal ? `Vía: ${canal}.` : '', descripcion.trim()].filter(Boolean)
    if (modoAcuerdo === 'calculado' && planCalculado) {
      const nombre = planCalculado.modalidad === 'judicial' ? 'AVENIMIENTO' : 'ACUERDO DE PAGO'
      return [`${nombre}: ${planCalculado.texto}`, ...extras].join('\n')
    }
    const iguales = new Set(cuotas.map((c) => Math.round(Number(c.monto)))).size === 1
    let texto = `ACUERDO DE PAGO: ${clp(Number(total))} en ${cuotas.length} cuota(s)`
      + (iguales ? ` de ${clp(Number(cuotas[0]?.monto))}` : ' de montos distintos')
    if (Number(pie) > 0) texto += `, pie de ${clp(Number(pie))} el ${fechaLegible(fechaPie)}`
    texto += `. Primera cuota vence el ${fechaLegible(cuotas[0]?.fecha ?? null)}, última el ${fechaLegible(cuotas.at(-1)?.fecha ?? null)}.`
    return [texto, ...extras].join('\n')
  }

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
                  <span>{nombreCuota(c.numero_cuota, vigente?.numero_cuotas, 'Cuota ')}</span>
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
          <FormPago key={idCuota} cobranzaId={cobranza.id} saldo={cobranza.monto_actual} modalidad={cobranza.tipo}
            cuota={cuotaPago}
            alTerminar={(p) => terminar(`Pago de ${clp(p.monto)} registrado${p.cuota != null ? ` (${nombreCuota(p.cuota, null, 'cuota ')})` : ''}.`)}
            alCancelar={() => setResultado('gestion')} />
        </>
      ) : (
        <form className="form-gestion" onSubmit={(e: FormEvent) => {
          e.preventDefault(); setError('')
          if (resultado === 'acuerdo') setConfirmando(true)
          else guardar.mutate()
        }}>
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
          ) : (<>
            {conCalculadora && (
              <div className="segmentos" role="group" aria-label="Cómo armar el acuerdo">
                <button type="button" className={modoAcuerdo === 'calculado' ? 'activo' : ''} onClick={() => setModoAcuerdo('calculado')}>
                  Calculado (3-6-9)
                </button>
                <button type="button" className={modoAcuerdo === 'manual' ? 'activo' : ''} onClick={() => setModoAcuerdo('manual')}>
                  Montos a mano
                </button>
              </div>
            )}
            {modoAcuerdo === 'calculado' ? (
              <AcuerdoCalculado cobranza={cobranza}
                alCambiar={(c, p) => { setCuerpoCalculado(c); setPlanCalculado(p ?? null) }} />
            ) : (
            <div className="acuerdo-manual">
              <div className="fila">
                <label>Monto total *<input type="number" min="1" value={total} required
                  onChange={(e) => { setTotal(e.target.value); setCuotasEditadas(null) }} /></label>
                <label>Pie<input type="number" min="0" value={pie}
                  onChange={(e) => { setPie(e.target.value); setCuotasEditadas(null) }} /></label>
                {Number(pie) > 0 && (
                  <label>Fecha del pie *<input type="date" value={fechaPie} required
                    onChange={(e) => setFechaPie(e.target.value)} /></label>
                )}
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
            )}
          </>))}

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
            disabled={guardar.isPending || (resultado === 'acuerdo' && (Boolean(vigente)
              || (modoAcuerdo === 'calculado' ? !cuerpoCalculado : !cuadra)))}>
            {guardar.isPending ? 'Guardando…' : textoBoton}
          </button>
          {confirmando && (
            <ConfirmarGestion
              titulo={modoAcuerdo === 'calculado' && planCalculado?.modalidad === 'judicial' ? 'Registrar avenimiento' : 'Registrar acuerdo de pago'}
              gestion={textoAcuerdo()}
              detalle={<p className="suave">El pie y cada cuota quedarán en tu agenda y en los avisos.</p>}
              confirmar="Sí, registrar acuerdo"
              pendiente={guardar.isPending}
              error={error}
              alConfirmar={() => { setError(''); guardar.mutate() }}
              alCancelar={() => { setConfirmando(false); setError('') }}
            />
          )}
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

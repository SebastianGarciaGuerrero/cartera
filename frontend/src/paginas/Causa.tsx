import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, mensajeDeError } from '../api/client'
import type { CausaDetalle, Embargo, EtapaProcesal, TipoTramite, TramiteRegistrado } from '../api/judicial'
import { Plata, clp, describirCambios, fechaHoraLegible, fechaLegible, fechaLocal, rutConPuntos } from '../componentes/utiles'
import { useConfirmacion } from '../componentes/ConfirmarGestion'
import { useAuth } from '../auth'
import {
  clasePlazo, textoPlazo, useCatalogos, useEquipoJudicial, useTiposTramite, useTribunales,
} from '../componentes/usarJudicial'

// Ficha de una causa: en qué etapa procesal está, qué hay que revisar y
// cuándo, y el registro en un paso del trámite siguiente (con su gasto).

const ETAPAS: EtapaProcesal[] = ['demanda', 'notificacion', 'embargo', 'defensa', 'remate']

export default function Causa() {
  const { id } = useParams()
  const qc = useQueryClient()
  const { data: causa, isLoading } = useQuery({
    queryKey: ['judicial', 'causa', id],
    queryFn: async () => (await api.get<CausaDetalle>(`/judicial/causas/${id}`)).data,
  })
  const { data: catalogos } = useCatalogos()
  const [editando, setEditando] = useState(false)
  const [propuesta, setPropuesta] = useState<string | null>(null)
  const { puede } = useAuth()
  const causas = puede('judicial_causas')
  const tramites = puede('judicial_tramites')

  const refrescar = () => {
    qc.invalidateQueries({ queryKey: ['judicial'] })
    for (const c of causa?.cobranzas ?? []) {
      qc.invalidateQueries({ queryKey: ['ciclo', c.id] })
      qc.invalidateQueries({ queryKey: ['cobranza', c.id] })
    }
  }

  if (isLoading || !causa) return <div className="pantalla-carga">Cargando causa…</div>

  const vigente = causa.estado === 'vigente'
  const indiceEtapa = ETAPAS.indexOf(causa.etapa_procesal)

  return (
    <>
      <header className="pagina-cabecera">
        <div>
          <Link to="/judicial" className="volver">← Bandeja judicial</Link>
          <h1>
            {causa.rol ? `Causa rol ${causa.rol}` : 'Causa sin rol'}{' '}
            <span className={`etiqueta ${vigente ? 'etiqueta-judicial' : 'etiqueta-archivada'}`}>
              {vigente ? 'Vigente' : `Terminada: ${catalogos?.resultados[causa.resultado ?? ''] ?? causa.resultado}`}
            </span>
          </h1>
          <p className="suave">
            {causa.caratula} · {causa.procedimiento_nombre}
            {causa.tribunal && ` · ${causa.tribunal}`}
          </p>
        </div>
      </header>

      <section className="ciclo">
        <ol className="ciclo-pasos">
          {ETAPAS.map((e, i) => {
            const estado = !vigente ? (i <= indiceEtapa ? 'hecho' : 'omitido')
              : i < indiceEtapa ? 'hecho' : i === indiceEtapa ? 'actual' : 'pendiente'
            return (
              <li key={e} className={`ciclo-paso ${estado}${i === 0 ? ' inicio' : ''}`}>
                <span className="ciclo-punto">{i + 1}</span>
                <span className="ciclo-nombre">{catalogos?.etapas[e] ?? e}</span>
              </li>
            )
          })}
        </ol>
        {vigente && (
          <div className="ciclo-pie">
            <div className="ciclo-estado">
              {causa.plazo_fecha ? (
                <>
                  <span className={`plazo ${clasePlazo(causa.plazo_fecha)}`}>{textoPlazo(causa.plazo_fecha)}</span>
                  <span className="suave"> ({fechaLegible(causa.plazo_fecha)})</span>
                  {causa.siguiente_nombre && <> · Próximo paso: <strong>{causa.siguiente_nombre}</strong></>}
                </>
              ) : <span className="suave">Sin plazo pendiente.</span>}
              <span className="suave"> · {causa.dias_sin_movimiento} días desde el último trámite</span>
              {causa.riesgo_abandono && (
                <div className="ciclo-alerta">
                  Más de 5 meses sin trámites: riesgo de abandono del procedimiento (6 meses).
                </div>
              )}
            </div>
          </div>
        )}
      </section>

      {propuesta && vigente && causas && (
        <TerminarCausa causa={causa} resultadoInicial={propuesta} alTerminar={() => { setPropuesta(null); refrescar() }}
          alCancelar={() => setPropuesta(null)} aviso />
      )}

      <div className="ficha-grilla">
        <section className="tarjeta">
          <div className="tarjeta-cabecera">
            <h2>Datos de la causa</h2>
            {vigente && !editando && causas && (
              <button className="btn btn-chico btn-secundario" onClick={() => setEditando(true)}>Corregir</button>
            )}
          </div>
          {editando ? (
            <EditarCausa causa={causa} alTerminar={() => { setEditando(false); refrescar() }} />
          ) : (
            <dl className="datos">
              <dt>Rol</dt><dd className="mono">{causa.rol ?? '—'}</dd>
              <dt>Tribunal</dt><dd>{causa.tribunal ?? 'Aún no se distribuye'}</dd>
              <dt>Procedimiento</dt><dd>{causa.procedimiento_nombre}</dd>
              <dt>Ingreso</dt><dd>{fechaLegible(causa.fecha_ingreso)}</dd>
              {causa.fecha_termino && <><dt>Término</dt><dd>{fechaLegible(causa.fecha_termino)}</dd></>}
              <dt>Cliente</dt><dd>{causa.cliente}</dd>
              <dt>Demandado</dt>
              <dd>{causa.deudor} <span className="mono suave">{rutConPuntos(causa.deudor_rut)}</span></dd>
              <dt>Cuantía</dt><dd>{causa.cuantia ? <Plata valor={causa.cuantia} /> : '—'}</dd>
              <dt>Abogado</dt><dd>{causa.abogado ?? 'Sin asignar'}</dd>
              <dt>Procurador</dt><dd>{causa.procurador ?? 'Sin asignar'}</dd>
            </dl>
          )}
          {causa.observaciones && !editando && <p className="observaciones">{causa.observaciones}</p>}

          <h2 className="separado">Cobranzas en la demanda</h2>
          <ul className="lista-cobranzas">
            {causa.cobranzas.map((c) => (
              <li key={c.id}>
                <Link to={`/cobranzas/${c.id}`} className="mono negrita">N° {c.numero}</Link>
                <span className="der"><Plata valor={c.monto_actual} /></span>
                <span className="suave">
                  {c.tipo_documento}{c.numero_documento && ` N° ${c.numero_documento}`}
                  {c.id_externo && ` · ID ${c.id_externo}`}
                </span>
                <span className={`etiqueta etiqueta-${c.estado}`}>{c.estado.replace('_', ' ')}</span>
              </li>
            ))}
          </ul>
          {vigente && causas && <AgregarCobranza causa={causa} alAgregar={refrescar} />}

          {vigente && causas && (
            <details className="separado">
              <summary className="btn btn-secundario btn-chico">Terminar la causa</summary>
              <TerminarCausa causa={causa} resultadoInicial="pagada" alTerminar={refrescar} />
            </details>
          )}
        </section>

        <section className="tarjeta">
          {vigente && tramites && <RegistrarTramite causa={causa} alRegistrar={(r) => {
            refrescar()
            if (r.propone_resultado) setPropuesta(r.propone_resultado)
          }} />}

          <h2>Trámites ({causa.tramites.length})</h2>
          <ul className="linea-tiempo">
            {causa.tramites.map((t) => (
              <li key={t.id} className={t.tipo_id ? '' : 'tramite-observacion'}>
                <div className="gestion-cabecera">
                  <span className="gestion-tipo">{t.tipo_nombre ?? 'Observación'}</span>
                  <span className="suave">
                    {t.usuario_nombre && <span className="gestion-usuario">{t.usuario_nombre}</span>}
                    {fechaLegible(t.fecha)}
                  </span>
                </div>
                {t.descripcion && <p>{t.descripcion}</p>}
                {t.plazo_fecha && (
                  <div className="proximo-aviso">
                    Revisar el {fechaLegible(t.plazo_fecha)}{t.siguiente_nombre && ` · luego: ${t.siguiente_nombre}`}
                  </div>
                )}
                <div className="nota">Registrado {fechaHoraLegible(t.created_at)}</div>
              </li>
            ))}
          </ul>
        </section>
      </div>

      <Embargos causa={causa} alCambiar={refrescar} />
      <GastosCausa causa={causa} alCambiar={refrescar} />
    </>
  )
}

// ------------------------------------------------------------------ trámite

function RegistrarTramite({ causa, alRegistrar }: {
  causa: CausaDetalle; alRegistrar: (r: TramiteRegistrado) => void
}) {
  const { data: tipos } = useTiposTramite()
  const { data: catalogos } = useCatalogos()
  const [tipoId, setTipoId] = useState<string>(causa.siguiente_id ? String(causa.siguiente_id) : '')
  const [filtro, setFiltro] = useState('')
  const [fecha, setFecha] = useState(fechaLocal())
  const [descripcion, setDescripcion] = useState('')
  const [plazo, setPlazo] = useState('')
  const [conGasto, setConGasto] = useState(false)
  const [gasto, setGasto] = useState({ monto: '', proveedor: '', numero_boleta: '', tipo: 'receptor' })
  const [error, setError] = useState('')
  const [hecho, setHecho] = useState('')

  // Al cambiar el plazo pendiente de la causa, se propone el trámite esperado.
  useEffect(() => { setTipoId(causa.siguiente_id ? String(causa.siguiente_id) : '') }, [causa.siguiente_id])

  const tipo = tipos?.find((t) => String(t.id) === tipoId)
  useEffect(() => { setConGasto(Boolean(tipo?.genera_gasto)) }, [tipo?.id, tipo?.genera_gasto])

  const visibles = useMemo(() => {
    const f = filtro.trim().toLowerCase()
    const lista = (tipos ?? []).filter((t) => !f || t.nombre.toLowerCase().includes(f))
    const grupos = new Map<string, TipoTramite[]>()
    for (const t of lista) {
      const clave = t.etapa ? (catalogos?.etapas[t.etapa] ?? t.etapa) : 'Otros y término'
      grupos.set(clave, [...(grupos.get(clave) ?? []), t])
    }
    return Array.from(grupos.entries())
  }, [tipos, filtro, catalogos])

  const plazoAuto = tipo?.plazo_dias != null ? sumarDias(fecha, tipo.plazo_dias) : null
  const siguiente = tipo?.siguiente_id ? tipos?.find((t) => t.id === tipo.siguiente_id) : null

  const guardar = useMutation({
    mutationFn: async () => (await api.post<TramiteRegistrado>(`/judicial/causas/${causa.id}/tramites`, {
      tipo_id: tipoId ? Number(tipoId) : null,
      fecha,
      descripcion: descripcion.trim() || null,
      plazo_fecha: plazo || null,
      gasto: conGasto && gasto.monto ? {
        monto: Number(gasto.monto), proveedor: gasto.proveedor || null,
        numero_boleta: gasto.numero_boleta || null, tipo: gasto.tipo, fecha,
      } : null,
    })).data,
    onSuccess: (r) => {
      setDescripcion(''); setPlazo(''); setFiltro(''); setError('')
      setGasto({ monto: '', proveedor: '', numero_boleta: '', tipo: 'receptor' })
      setHecho(r.tramite.tipo_nombre ? `Registrado: ${r.tramite.tipo_nombre}.` : 'Observación registrada.')
      alRegistrar(r)
    },
    onError: (e) => setError(mensajeDeError(e)),
  })

  const { pedir, modal } = useConfirmacion()
  function confirmar() {
    let texto = `TRÁMITE JUDICIAL (rol ${causa.rol ?? 'sin rol'}): ${tipo?.nombre ?? 'Observación'}`
    if (descripcion.trim()) texto += `. ${descripcion.trim()}`
    const plazoFinal = plazo || plazoAuto
    if (plazoFinal && tipo) texto += `. Plazo: ${fechaLegible(plazoFinal)}`
    if (conGasto && gasto.monto) texto += `. Gasto: ${clp(Number(gasto.monto))}`
    pedir({ titulo: 'Registrar trámite', gestion: texto + '.', confirmar: 'Sí, registrar', accion: () => guardar.mutateAsync() })
  }

  return (
    <form className="form-gestion" onSubmit={(e) => { e.preventDefault(); confirmar() }}>
      {modal}
      <h2>Registrar trámite</h2>
      <div className="fila">
        <input placeholder="Buscar trámite…" value={filtro} onChange={(e) => setFiltro(e.target.value)} />
        <select value={tipoId} onChange={(e) => setTipoId(e.target.value)} aria-label="Trámite">
          <option value="">Solo una observación</option>
          {visibles.map(([grupo, lista]) => (
            <optgroup key={grupo} label={grupo}>
              {lista.map((t) => <option key={t.id} value={t.id}>{t.nombre}</option>)}
            </optgroup>
          ))}
        </select>
      </div>
      {tipo && (
        <p className={`nota${tipo.alerta ? ' nota-alerta' : ''}`}>
          {plazoAuto ? `Revisar en ${tipo.plazo_dias} días (${fechaLegible(plazoAuto)})` : 'Sin plazo de seguimiento'}
          {siguiente && ` · luego suele venir: ${siguiente.nombre}`}
          {tipo.etapa && ` · etapa: ${catalogos?.etapas[tipo.etapa] ?? tipo.etapa}`}
          {tipo.nota && <><br />{tipo.nota}</>}
        </p>
      )}
      <div className="fila">
        <label>Fecha<input type="date" value={fecha} max={fechaLocal()} onChange={(e) => setFecha(e.target.value)} /></label>
        <label>Plazo a mano<input type="date" value={plazo} min={fecha} onChange={(e) => setPlazo(e.target.value)} /></label>
      </div>
      <textarea rows={2} placeholder={tipoId ? 'Detalle (opcional)' : 'Escriba la observación'}
        value={descripcion} onChange={(e) => setDescripcion(e.target.value)} />
      <label className="check">
        <input type="checkbox" checked={conGasto} onChange={(e) => setConGasto(e.target.checked)} />
        Este trámite tuvo un gasto (receptor, conservador…)
      </label>
      {conGasto && (
        <div className="fila">
          <label>Monto<input type="number" min={1} value={gasto.monto}
            onChange={(e) => setGasto({ ...gasto, monto: e.target.value })} /></label>
          <label>Tipo
            <select value={gasto.tipo} onChange={(e) => setGasto({ ...gasto, tipo: e.target.value })}>
              {Object.entries(catalogos?.tipos_gasto ?? {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
          <label>Receptor / proveedor<input value={gasto.proveedor}
            onChange={(e) => setGasto({ ...gasto, proveedor: e.target.value })} /></label>
          <label>N° boleta<input value={gasto.numero_boleta}
            onChange={(e) => setGasto({ ...gasto, numero_boleta: e.target.value })} /></label>
        </div>
      )}
      {error && <div className="alerta-error">{error}</div>}
      {hecho && !error && <div className="alerta-exito">{hecho}</div>}
      <div>
        <button className="btn btn-primario" disabled={guardar.isPending || (!tipoId && !descripcion.trim())}>
          {guardar.isPending ? 'Guardando…' : 'Registrar'}
        </button>
      </div>
    </form>
  )
}

function sumarDias(iso: string, dias: number): string {
  const [a, m, d] = iso.split('-').map(Number)
  return fechaLocal(new Date(a, m - 1, d + dias))
}

// ------------------------------------------------------------------ datos

function EditarCausa({ causa, alTerminar }: { causa: CausaDetalle; alTerminar: () => void }) {
  const { data: tribunales } = useTribunales()
  const { data: equipo } = useEquipoJudicial()
  const { data: catalogos } = useCatalogos()
  const [datos, setDatos] = useState({
    rol: causa.rol ?? '', tribunal_id: causa.tribunal_id ? String(causa.tribunal_id) : '',
    procedimiento: causa.procedimiento, abogado_id: causa.abogado_id ?? '',
    procurador_id: causa.procurador_id ?? '', caratula: causa.caratula ?? '',
    cuantia: causa.cuantia ?? '', etapa_procesal: causa.etapa_procesal,
  })
  const [error, setError] = useState('')
  const guardar = useMutation({
    mutationFn: () => api.put(`/judicial/causas/${causa.id}`, {
      ...datos, rol: datos.rol.trim() || null, tribunal_id: datos.tribunal_id ? Number(datos.tribunal_id) : null,
      abogado_id: datos.abogado_id || null, procurador_id: datos.procurador_id || null,
      cuantia: datos.cuantia === '' ? null : Number(datos.cuantia), caratula: datos.caratula || null,
    }),
    onSuccess: alTerminar,
    onError: (e) => setError(mensajeDeError(e)),
  })
  const campo = (k: keyof typeof datos) => ({
    value: datos[k], onChange: (e: { target: { value: string } }) => setDatos({ ...datos, [k]: e.target.value }),
  })
  const { pedir, modal } = useConfirmacion()
  function confirmar() {
    // Lo que cambió, con nombres (tribunal y personas) en vez de ids.
    const tribunal = (id: string) => tribunales?.find((t) => String(t.id) === id)?.nombre ?? ''
    const persona = (id: string) => equipo?.find((u) => u.id === id)?.nombre ?? ''
    const legible = (x: typeof datos) => ({
      rol: x.rol.trim(), tribunal: tribunal(x.tribunal_id), procedimiento: catalogos?.procedimientos[x.procedimiento] ?? x.procedimiento,
      abogado: persona(x.abogado_id), procurador: persona(x.procurador_id), caratula: x.caratula, cuantia: x.cuantia,
      etapa: catalogos?.etapas[x.etapa_procesal as EtapaProcesal] ?? x.etapa_procesal,
    })
    const antes = {
      rol: causa.rol ?? '', tribunal_id: causa.tribunal_id ? String(causa.tribunal_id) : '', procedimiento: causa.procedimiento,
      abogado_id: causa.abogado_id ?? '', procurador_id: causa.procurador_id ?? '', caratula: causa.caratula ?? '',
      cuantia: causa.cuantia ?? '', etapa_procesal: causa.etapa_procesal,
    }
    const detalle = describirCambios(legible(antes), legible(datos), {
      rol: 'Rol', tribunal: 'Tribunal', procedimiento: 'Procedimiento', abogado: 'Abogado', procurador: 'Procurador',
      caratula: 'Carátula', cuantia: 'Cuantía', etapa: 'Etapa procesal',
    })
    if (!detalle) { alTerminar(); return }
    pedir({ titulo: 'Guardar cambios de la causa', gestion: `DATOS DE LA CAUSA MODIFICADOS: ${detalle}.`,
      confirmar: 'Sí, guardar', accion: () => guardar.mutateAsync() })
  }
  return (
    <form className="form-grilla" onSubmit={(e) => { e.preventDefault(); confirmar() }}>
      {modal}
      <label>Rol<input {...campo('rol')} /></label>
      <label>Tribunal
        <select {...campo('tribunal_id')}>
          <option value="">Aún no se distribuye</option>
          {tribunales?.map((t) => <option key={t.id} value={t.id}>{t.nombre}</option>)}
        </select>
      </label>
      <label>Procedimiento
        <select {...campo('procedimiento')}>
          {Object.entries(catalogos?.procedimientos ?? {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </label>
      <label>Etapa (corrección)
        <select {...campo('etapa_procesal')}>
          {ETAPAS.map((e) => <option key={e} value={e}>{catalogos?.etapas[e] ?? e}</option>)}
        </select>
      </label>
      <label>Abogado
        <select {...campo('abogado_id')}>
          <option value="">Sin asignar</option>
          {equipo?.map((u) => <option key={u.id} value={u.id}>{u.nombre}</option>)}
        </select>
      </label>
      <label>Procurador
        <select {...campo('procurador_id')}>
          <option value="">Sin asignar</option>
          {equipo?.map((u) => <option key={u.id} value={u.id}>{u.nombre}</option>)}
        </select>
      </label>
      <label>Cuantía<input type="number" min={0} {...campo('cuantia')} /></label>
      <label className="ancho-completo">Carátula<input {...campo('caratula')} /></label>
      {error && <div className="alerta-error ancho-completo">{error}</div>}
      <div className="acciones-fila ancho-completo">
        <button className="btn btn-primario" disabled={guardar.isPending}>Guardar</button>
        <button type="button" className="btn btn-secundario" onClick={alTerminar}>Cancelar</button>
      </div>
    </form>
  )
}

function AgregarCobranza({ causa, alAgregar }: { causa: CausaDetalle; alAgregar: () => void }) {
  const [abierto, setAbierto] = useState(false)
  const [error, setError] = useState('')
  const { data: otras } = useQuery({
    queryKey: ['cobranzas-deudor', causa.deudor_id, causa.cliente_id],
    enabled: abierto,
    queryFn: async () => (await api.get<{ id: string; numero: number; estado: string; etapa?: string; monto_actual: string }[]>(
      '/cobranzas/', { params: { deudor_id: causa.deudor_id, cliente_id: causa.cliente_id, limit: 100 } })).data,
  })
  const enCausa = new Set(causa.cobranzas.map((c) => c.id))
  const disponibles = (otras ?? []).filter((c) => !enCausa.has(c.id) && ['activa', 'acuerdo_pago'].includes(c.estado))
  const agregar = useMutation({
    mutationFn: (cobranza_id: string) => api.post(`/judicial/causas/${causa.id}/cobranzas`, { cobranza_id }),
    onSuccess: () => { setAbierto(false); alAgregar() },
    onError: (e) => setError(mensajeDeError(e)),
  })
  const { pedir, modal } = useConfirmacion()
  if (!abierto) {
    return <button className="btn btn-chico btn-secundario" onClick={() => setAbierto(true)}>Sumar otra cobranza del deudor</button>
  }
  return (
    <div className="sumar-cobranza">
      {disponibles.length === 0 ? <p className="suave">El deudor no tiene otras cobranzas abiertas con este cliente.</p> : (
        <ul className="lista-elegibles">
          {disponibles.map((c) => (
            <li key={c.id}>
              <span className="mono negrita">N° {c.numero}</span> <Plata valor={c.monto_actual} />{' '}
              <button className="btn btn-chico btn-secundario" disabled={agregar.isPending}
                onClick={() => pedir({
                  titulo: `Sumar la cobranza N° ${c.numero} a la causa`,
                  gestion: `DEMANDA PRESENTADA en la cobranza N° ${c.numero}: se suma a la causa rol ${causa.rol ?? 'sin rol'}`
                    + `${causa.tribunal ? `, ${causa.tribunal}` : ''}. Pasa a judicial y no vuelve atrás.`,
                  confirmar: 'Sí, sumar', accion: () => agregar.mutateAsync(c.id),
                })}>Sumar a la causa</button>
            </li>
          ))}
        </ul>
      )}
      {error && <div className="alerta-error">{error}</div>}
      {modal}
      <button className="btn-texto" onClick={() => setAbierto(false)}>Cerrar</button>
    </div>
  )
}

function TerminarCausa({ causa, resultadoInicial, alTerminar, alCancelar, aviso }: {
  causa: CausaDetalle; resultadoInicial: string; alTerminar: () => void; alCancelar?: () => void; aviso?: boolean
}) {
  const { data: catalogos } = useCatalogos()
  const [resultado, setResultado] = useState(resultadoInicial)
  const [motivo, setMotivo] = useState('')
  const [fecha, setFecha] = useState(fechaLocal())
  const [nota, setNota] = useState('')
  const [error, setError] = useState('')
  const terminar = useMutation({
    mutationFn: () => api.post(`/judicial/causas/${causa.id}/terminar`, {
      resultado, fecha, nota: nota || null, motivo_cierre: resultado === 'castigo' ? (motivo || null) : null,
    }),
    onSuccess: alTerminar,
    onError: (e) => setError(mensajeDeError(e)),
  })
  const { pedir, modal } = useConfirmacion()
  return (
    <div className={aviso ? 'aviso-termino tarjeta' : 'form-termino'}>
      {modal}
      {aviso && (
        <p><strong>Este trámite suele cerrar la causa</strong> como «{catalogos?.resultados[resultadoInicial] ?? resultadoInicial}».
          ¿La terminamos? Las cobranzas sin otra causa vigente quedan cerradas.</p>
      )}
      <div className="fila">
        <label>Resultado
          <select value={resultado} onChange={(e) => setResultado(e.target.value)}>
            {Object.entries(catalogos?.resultados ?? {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        {resultado === 'castigo' && (
          <label>Motivo
            <select value={motivo} onChange={(e) => setMotivo(e.target.value)}>
              <option value="">Elegir…</option>
              {Object.entries(catalogos?.motivos_cierre ?? {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
        )}
        <label>Fecha<input type="date" value={fecha} max={fechaLocal()} onChange={(e) => setFecha(e.target.value)} /></label>
      </div>
      <textarea rows={2} placeholder="Nota (opcional)" value={nota} onChange={(e) => setNota(e.target.value)} />
      {error && <div className="alerta-error">{error}</div>}
      <div className="acciones-fila">
        <button className="btn btn-primario" disabled={terminar.isPending || (resultado === 'castigo' && !motivo)}
          onClick={() => pedir({
            titulo: 'Terminar la causa',
            gestion: `CAUSA TERMINADA (${causa.rol ?? 'sin rol'}): ${catalogos?.resultados[resultado] ?? resultado}.`
              + (resultado === 'castigo' && motivo ? ` Cobranza cerrada: ${catalogos?.motivos_cierre[motivo] ?? motivo}.` : '')
              + (nota.trim() ? ` ${nota.trim()}` : ''),
            detalle: <p className="suave">Las cobranzas sin otra causa vigente quedan cerradas.</p>,
            confirmar: 'Sí, terminar', accion: () => terminar.mutateAsync(),
          })}>Terminar causa</button>
        {alCancelar && <button className="btn btn-secundario" onClick={alCancelar}>Todavía no</button>}
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ embargos

function Embargos({ causa, alCambiar }: { causa: CausaDetalle; alCambiar: () => void }) {
  const { puede } = useAuth()
  const tramites = puede('judicial_tramites')
  const { data: catalogos } = useCatalogos()
  const [nuevo, setNuevo] = useState(false)
  const [editando, setEditando] = useState<Embargo | null>(null)
  return (
    <section className="tarjeta separado">
      <div className="tarjeta-cabecera">
        <h2>Embargos ({causa.embargos.length})</h2>
        {!nuevo && tramites && <button className="btn btn-chico btn-secundario" onClick={() => setNuevo(true)}>Registrar embargo</button>}
      </div>
      {nuevo && <FormEmbargo causaId={causa.id} alTerminar={() => { setNuevo(false); alCambiar() }} />}
      {causa.embargos.length > 0 && (
        <div className="tabla-desplazable">
          <table className="tabla">
            <thead><tr><th>Bien</th><th>Descripción</th><th>Estado</th><th>Traba</th><th className="der">Tasación</th><th className="der">Remate</th><th></th></tr></thead>
            <tbody>
              {causa.embargos.map((e) => (
                <tr key={e.id}>
                  <td>{catalogos?.tipos_bien[e.tipo_bien] ?? e.tipo_bien}</td>
                  <td>{e.descripcion}{e.inscripcion && <div className="suave">{e.inscripcion}</div>}</td>
                  <td><span className={`etiqueta embargo-${e.estado}`}>{catalogos?.estados_embargo[e.estado] ?? e.estado}</span></td>
                  <td>{fechaLegible(e.fecha_traba)}</td>
                  <td className="der">{e.monto_tasacion ? <Plata valor={e.monto_tasacion} /> : '—'}</td>
                  <td className="der">{e.monto_remate ? <Plata valor={e.monto_remate} /> : '—'}</td>
                  <td>{tramites && <button className="btn btn-chico btn-secundario" onClick={() => setEditando(e)}>Actualizar</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {causa.embargos.length === 0 && !nuevo && <p className="suave">Sin embargos registrados.</p>}
      {editando && (
        <div className="modal-fondo" onClick={() => setEditando(null)}>
          <div className="modal modal-ancho" onClick={(ev) => ev.stopPropagation()}>
            <h3>Actualizar embargo</h3>
            <FormEmbargo causaId={causa.id} embargo={editando} alTerminar={() => { setEditando(null); alCambiar() }} />
          </div>
        </div>
      )}
    </section>
  )
}

function FormEmbargo({ causaId, embargo, alTerminar }: { causaId: string; embargo?: Embargo; alTerminar: () => void }) {
  const { data: catalogos } = useCatalogos()
  const [d, setD] = useState({
    tipo_bien: embargo?.tipo_bien ?? 'muebles', descripcion: embargo?.descripcion ?? '',
    estado: embargo?.estado ?? 'trabado', fecha_traba: embargo?.fecha_traba ?? fechaLocal(),
    inscripcion: embargo?.inscripcion ?? '', depositario: embargo?.depositario ?? '',
    monto_tasacion: embargo?.monto_tasacion ?? '', fecha_remate: embargo?.fecha_remate ?? '',
    monto_remate: embargo?.monto_remate ?? '', observaciones: embargo?.observaciones ?? '',
  })
  const [error, setError] = useState('')
  const guardar = useMutation({
    mutationFn: () => {
      const cuerpo = {
        ...d, fecha_traba: d.fecha_traba || null, fecha_remate: d.fecha_remate || null,
        monto_tasacion: d.monto_tasacion === '' ? null : Number(d.monto_tasacion),
        monto_remate: d.monto_remate === '' ? null : Number(d.monto_remate),
        inscripcion: d.inscripcion || null, depositario: d.depositario || null, observaciones: d.observaciones || null,
      }
      return embargo ? api.put(`/judicial/embargos/${embargo.id}`, cuerpo)
        : api.post(`/judicial/causas/${causaId}/embargos`, cuerpo)
    },
    onSuccess: alTerminar,
    onError: (e) => setError(mensajeDeError(e)),
  })
  const campo = (k: keyof typeof d) => ({
    value: d[k] ?? '', onChange: (e: { target: { value: string } }) => setD({ ...d, [k]: e.target.value }),
  })
  const { pedir, modal } = useConfirmacion()
  function confirmar() {
    if (!embargo) {
      pedir({ titulo: 'Registrar embargo', confirmar: 'Sí, registrar', accion: () => guardar.mutateAsync(),
        gestion: `EMBARGO REGISTRADO: ${catalogos?.tipos_bien[d.tipo_bien] ?? d.tipo_bien} — ${d.descripcion}, `
          + `${(catalogos?.estados_embargo[d.estado] ?? d.estado).toLowerCase()}.` })
      return
    }
    const legible = (x: Record<string, unknown>) => ({ ...x, tipo_bien: catalogos?.tipos_bien[String(x.tipo_bien)] ?? x.tipo_bien,
      estado: catalogos?.estados_embargo[String(x.estado)] ?? x.estado })
    const detalle = describirCambios(legible(embargo as unknown as Record<string, unknown>), legible(d), {
      tipo_bien: 'Tipo de bien', descripcion: 'Descripción', estado: 'Estado', fecha_traba: 'Fecha de traba',
      inscripcion: 'Inscripción', depositario: 'Depositario', monto_tasacion: 'Tasación', fecha_remate: 'Fecha de remate',
      monto_remate: 'Monto del remate', observaciones: 'Observaciones',
    })
    if (!detalle) { alTerminar(); return }
    pedir({ titulo: 'Actualizar embargo', gestion: `EMBARGO ACTUALIZADO (${embargo.descripcion}): ${detalle}.`,
      confirmar: 'Sí, guardar', accion: () => guardar.mutateAsync() })
  }
  return (
    <form className="form-grilla" onSubmit={(e) => { e.preventDefault(); confirmar() }}>
      {modal}
      <label>Bien
        <select {...campo('tipo_bien')}>
          {Object.entries(catalogos?.tipos_bien ?? {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </label>
      <label>Estado
        <select {...campo('estado')}>
          {Object.entries(catalogos?.estados_embargo ?? {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </label>
      <label className="ancho-completo">Descripción
        <input {...campo('descripcion')} placeholder="Patente, rol de avalúo, banco y cuenta, especies…" required />
      </label>
      <label>Fecha de traba<input type="date" {...campo('fecha_traba')} /></label>
      <label>Inscripción<input {...campo('inscripcion')} placeholder="Conservador / Registro de Vehículos" /></label>
      <label>Depositario<input {...campo('depositario')} /></label>
      <label>Tasación<input type="number" min={0} {...campo('monto_tasacion')} /></label>
      <label>Fecha de remate<input type="date" {...campo('fecha_remate')} /></label>
      <label>Monto del remate<input type="number" min={0} {...campo('monto_remate')} /></label>
      {error && <div className="alerta-error ancho-completo">{error}</div>}
      <div className="acciones-fila ancho-completo">
        <button className="btn btn-primario" disabled={guardar.isPending}>Guardar</button>
        <button type="button" className="btn btn-secundario" onClick={alTerminar}>Cancelar</button>
      </div>
    </form>
  )
}

// ------------------------------------------------------------------ gastos

function GastosCausa({ causa, alCambiar }: { causa: CausaDetalle; alCambiar: () => void }) {
  const { data: catalogos } = useCatalogos()
  const [nuevo, setNuevo] = useState(false)
  const [d, setD] = useState({ fecha: fechaLocal(), tipo: 'receptor', concepto: '', monto: '', proveedor: '', numero_boleta: '' })
  const [error, setError] = useState('')
  const guardar = useMutation({
    mutationFn: () => api.post('/gastos/', {
      ...d, causa_id: causa.id, monto: Number(d.monto), proveedor: d.proveedor || null, numero_boleta: d.numero_boleta || null,
    }),
    onSuccess: () => { setNuevo(false); setD({ ...d, concepto: '', monto: '', numero_boleta: '' }); alCambiar() },
    onError: (e) => setError(mensajeDeError(e)),
  })
  const { puede } = useAuth()
  const { pedir, modal } = useConfirmacion()
  function confirmar() {
    pedir({
      titulo: 'Registrar gasto', confirmar: 'Sí, registrar', accion: () => guardar.mutateAsync(),
      gestion: `GASTO REGISTRADO: ${catalogos?.tipos_gasto[d.tipo] ?? d.tipo} — ${d.concepto.trim()}, ${clp(Number(d.monto))}`
        + (d.proveedor.trim() ? `, ${d.proveedor.trim()}` : '') + (d.numero_boleta.trim() ? `, boleta N° ${d.numero_boleta.trim()}` : '')
        + (causa.rol ? ` (causa rol ${causa.rol})` : '') + '.',
    })
  }
  return (
    <section className="tarjeta separado">
      <div className="tarjeta-cabecera">
        <h2>Gastos de la causa · <Plata valor={causa.total_gastos} /></h2>
        <div className="acciones-fila">
          {!nuevo && <button className="btn btn-chico btn-secundario" onClick={() => setNuevo(true)}>Registrar gasto</button>}
          {puede('ver_totales') && (
            <Link className="btn btn-chico btn-secundario" to={`/gastos?cliente=${causa.cliente_id}`}>Gastos del cliente</Link>
          )}
        </div>
      </div>
      {nuevo && (
        <form className="form-grilla" onSubmit={(e) => { e.preventDefault(); confirmar() }}>
          {modal}
          <label>Fecha<input type="date" value={d.fecha} max={fechaLocal()} onChange={(e) => setD({ ...d, fecha: e.target.value })} /></label>
          <label>Tipo
            <select value={d.tipo} onChange={(e) => setD({ ...d, tipo: e.target.value })}>
              {Object.entries(catalogos?.tipos_gasto ?? {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
          <label className="ancho-completo">Concepto<input value={d.concepto} required minLength={2}
            onChange={(e) => setD({ ...d, concepto: e.target.value })} placeholder="Búsqueda, notificación art. 44…" /></label>
          <label>Monto<input type="number" min={1} required value={d.monto} onChange={(e) => setD({ ...d, monto: e.target.value })} /></label>
          <label>Receptor / proveedor<input value={d.proveedor} onChange={(e) => setD({ ...d, proveedor: e.target.value })} /></label>
          <label>N° boleta<input value={d.numero_boleta} onChange={(e) => setD({ ...d, numero_boleta: e.target.value })} /></label>
          {error && <div className="alerta-error ancho-completo">{error}</div>}
          <div className="acciones-fila ancho-completo">
            <button className="btn btn-primario" disabled={guardar.isPending}>Guardar</button>
            <button type="button" className="btn btn-secundario" onClick={() => setNuevo(false)}>Cancelar</button>
          </div>
        </form>
      )}
      {causa.gastos.length > 0 ? (
        <table className="tabla">
          <thead><tr><th>Fecha</th><th>Concepto</th><th>Proveedor</th><th className="der">Monto</th><th>Estado</th></tr></thead>
          <tbody>
            {causa.gastos.map((g) => (
              <tr key={g.id}>
                <td>{fechaLegible(g.fecha)}</td>
                <td>{g.concepto}<div className="suave">{catalogos?.tipos_gasto[g.tipo] ?? g.tipo}</div></td>
                <td>{g.proveedor ?? '—'}{g.numero_boleta && <div className="suave">Boleta {g.numero_boleta}</div>}</td>
                <td className="der"><Plata valor={g.monto} /></td>
                <td><span className={`etiqueta gasto-${g.estado}`}>{catalogos?.estados_gasto[g.estado] ?? g.estado}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : !nuevo && <p className="suave">Sin gastos registrados.</p>}
    </section>
  )
}

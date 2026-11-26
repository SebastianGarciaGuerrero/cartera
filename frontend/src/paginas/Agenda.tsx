import { useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, mensajeDeError } from '../api/client'
import { useAuth } from '../auth'
import type { ItemAgenda, SeccionAgenda, TipoItemAgenda, TipoRecordatorio, Usuario } from '../api/tipos'
import { Plata, fechaLegible } from '../componentes/utiles'

// Agenda: lo que hay que hacer cada día, armado solo con lo que ya está en
// el sistema (próximos contactos y promesas de las gestiones, cuotas por
// vencer, acuerdos que dejaron de pagarse) más los recordatorios que cada
// uno se anota. Cada día se ordena por secciones: llamadas, WhatsApp,
// correos, cuotas vencidas…

const MESES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio',
  'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
const DIAS = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']

export const ESTILO_TIPO: Record<TipoItemAgenda, { nombre: string; color: string }> = {
  baja: { nombre: 'Acuerdo para baja', color: '#B42318' },
  recordatorio: { nombre: 'Recordatorio', color: '#7F77DD' },
  promesa: { nombre: 'Promesa de pago', color: '#EF9F27' },
  cuota: { nombre: 'Cuota', color: '#1D9E75' },
  contacto: { nombre: 'Contacto', color: '#378ADD' },
  plazo: { nombre: 'Plazo judicial', color: '#D85A30' },
}

// Orden y nombre de las secciones del día.
export const SECCIONES: [SeccionAgenda, string][] = [
  ['bajas', 'Acuerdos para dar de baja'], ['cuotas_vencidas', 'Cuotas vencidas'],
  ['cuotas', 'Cuotas que vencen'], ['promesas', 'Promesas de pago'], ['llamadas', 'Llamadas'],
  ['whatsapp', 'WhatsApp y SMS'], ['correos', 'Correos'], ['visitas', 'Visitas'],
  ['plazos', 'Plazos judiciales'], ['tareas', 'Otras tareas'],
]

export function porSeccion(items: ItemAgenda[]): { seccion: SeccionAgenda; nombre: string; items: ItemAgenda[] }[] {
  return SECCIONES
    .map(([seccion, nombre]) => ({ seccion, nombre, items: items.filter((i) => (i.seccion ?? 'tareas') === seccion) }))
    .filter((g) => g.items.length > 0)
}

const TIPOS_RECORDATORIO: [TipoRecordatorio, string][] = [
  ['llamada', 'Llamada'], ['whatsapp', 'WhatsApp'], ['correo', 'Correo'], ['visita', 'Visita'], ['tarea', 'Otra tarea'],
]

const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

export default function Agenda() {
  const { usuario } = useAuth()
  const qc = useQueryClient()
  const puedeVerEquipo = usuario?.rol === 'admin' || usuario?.rol === 'supervisor'
  const hoy = iso(new Date())
  const [mes, setMes] = useState(() => { const d = new Date(); return new Date(d.getFullYear(), d.getMonth(), 1) })
  const [dia, setDia] = useState<string>(hoy)
  const [quien, setQuien] = useState<string>('yo')   // 'yo' | 'todos' | id de usuario

  const filtro = quien === 'todos' ? { todos: true } : quien === 'yo' ? {} : { usuario_id: quien }

  const { data: equipo } = useQuery({
    queryKey: ['usuarios'],
    enabled: usuario?.rol === 'admin',
    queryFn: async () => (await api.get<Usuario[]>('/usuarios/')).data,
  })

  // La grilla muestra semanas completas: se pide desde el lunes de la
  // primera semana hasta el domingo de la última.
  const inicioGrilla = useMemo(() => {
    const d = new Date(mes)
    d.setDate(d.getDate() - ((d.getDay() + 6) % 7))
    return d
  }, [mes])
  const finGrilla = useMemo(() => {
    const d = new Date(inicioGrilla)
    d.setDate(d.getDate() + 41)
    return d
  }, [inicioGrilla])

  const { data: items } = useQuery({
    queryKey: ['agenda', iso(inicioGrilla), quien],
    queryFn: async () => (await api.get<ItemAgenda[]>('/agenda', {
      params: { desde: iso(inicioGrilla), hasta: iso(finGrilla), ...filtro },
    })).data,
  })
  const { data: pendientes } = useQuery({
    queryKey: ['agenda-hoy', quien],
    queryFn: async () => (await api.get<ItemAgenda[]>('/agenda/hoy', { params: filtro })).data,
  })

  const porDia = useMemo(() => {
    const m = new Map<string, ItemAgenda[]>()
    for (const i of items ?? []) m.set(i.fecha, [...(m.get(i.fecha) ?? []), i])
    return m
  }, [items])

  const atrasados = (pendientes ?? []).filter((i) => i.atrasado)

  const refrescar = () => {
    for (const queryKey of [['agenda'], ['agenda-hoy'], ['avisos'], ['seguimiento']]) qc.invalidateQueries({ queryKey })
  }
  const cerrar = useMutation({
    mutationFn: ({ id, estado }: { id: string; estado: 'hecho' | 'descartado' }) =>
      api.put(`/recordatorios/${id}`, { estado }),
    onSuccess: refrescar,
  })
  const darDeBaja = useMutation({
    mutationFn: (acuerdoId: string) => api.post(`/acuerdos/${acuerdoId}/baja`, {}),
    onSuccess: refrescar,
    onError: (e) => alert(mensajeDeError(e)),
  })

  const celdas = Array.from({ length: 42 }, (_, i) => {
    const d = new Date(inicioGrilla)
    d.setDate(d.getDate() + i)
    return d
  })
  const delDia = porDia.get(dia) ?? []

  function Item({ i }: { i: ItemAgenda }) {
    return (
      <li className={i.atrasado ? 'atrasado' : ''}>
        <span className="agenda-punto" style={{ background: ESTILO_TIPO[i.tipo].color }} />
        <div className="agenda-item">
          <div>
            <strong>{i.titulo}</strong>
            {i.hora && <span className="suave"> · {i.hora.slice(0, 5)}</span>}
            {i.atrasado && <span className="etiqueta etiqueta-castigo">{fechaLegible(i.fecha)}</span>}
          </div>
          {i.detalle && <div className="suave">{i.detalle}</div>}
          <div className="agenda-acciones">
            {i.causa_id && <Link to={`/judicial/causas/${i.causa_id}`}>Ver causa</Link>}
            {i.cobranza_id && (
              <Link to={`/cobranzas/${i.cobranza_id}${i.tipo === 'cuota' || i.tipo === 'baja' ? '?ver=pagos' : ''}`}>
                Cobranza N° {i.numero_cobranza}
              </Link>
            )}
            {i.monto != null && i.tipo !== 'recordatorio' && <span className="suave"><Plata valor={i.monto} /></span>}
            {i.tipo === 'baja' && i.acuerdo_id && (
              <button className="btn btn-chico btn-peligro" disabled={darDeBaja.isPending} onClick={() => {
                if (confirm(`¿Dar de baja el acuerdo de ${i.deudor}? Pasa a incumplido y la cobranza vuelve a gestión.`)) {
                  darDeBaja.mutate(i.acuerdo_id!)
                }
              }}>Dar de baja</button>
            )}
            {i.recordatorio_id && (
              <>
                <button className="btn btn-chico btn-secundario"
                  onClick={() => cerrar.mutate({ id: i.recordatorio_id!, estado: 'hecho' })}>Hecho</button>
                <button className="btn btn-chico btn-secundario"
                  onClick={() => cerrar.mutate({ id: i.recordatorio_id!, estado: 'descartado' })}>Descartar</button>
              </>
            )}
          </div>
        </div>
      </li>
    )
  }

  function Secciones({ lista, vacio }: { lista: ItemAgenda[]; vacio: string }) {
    if (lista.length === 0) return <p className="suave">{vacio}</p>
    return (
      <>
        {porSeccion(lista).map((g) => (
          <div key={g.seccion} className="agenda-seccion">
            <h3 className="subtitulo">{g.nombre} ({g.items.length})</h3>
            <ul className="agenda-lista">
              {g.items.map((i, n) => <Item key={n} i={i} />)}
            </ul>
          </div>
        ))}
      </>
    )
  }

  return (
    <>
      <header className="pagina-cabecera">
        <h1>Agenda</h1>
        {puedeVerEquipo && (
          <select value={quien} onChange={(e) => setQuien(e.target.value)}>
            <option value="yo">Mi agenda</option>
            <option value="todos">Todo el equipo</option>
            {equipo?.filter((u) => u.activo && u.id !== usuario?.id).map((u) => (
              <option key={u.id} value={u.id}>{u.nombre}</option>
            ))}
          </select>
        )}
      </header>

      {atrasados.length > 0 && (
        <section className="tarjeta">
          <h2>Atrasado ({atrasados.length})</h2>
          <Secciones lista={atrasados} vacio="" />
        </section>
      )}

      <div className="agenda-grilla">
        <section className="tarjeta">
          <div className="agenda-mes">
            <button className="btn btn-chico btn-secundario"
              onClick={() => setMes(new Date(mes.getFullYear(), mes.getMonth() - 1, 1))}>←</button>
            <strong>{MESES[mes.getMonth()]} {mes.getFullYear()}</strong>
            <button className="btn btn-chico btn-secundario"
              onClick={() => setMes(new Date(mes.getFullYear(), mes.getMonth() + 1, 1))}>→</button>
          </div>
          <div className="calendario">
            {DIAS.map((d) => <div key={d} className="calendario-dia-semana">{d}</div>)}
            {celdas.map((d) => {
              const clave = iso(d)
              const lista = porDia.get(clave) ?? []
              const tipos = Array.from(new Set(lista.map((i) => i.tipo)))
              return (
                <button key={clave} onClick={() => setDia(clave)}
                  className={['calendario-celda',
                    d.getMonth() !== mes.getMonth() ? 'fuera' : '',
                    clave === hoy ? 'hoy' : '', clave === dia ? 'elegido' : ''].join(' ')}>
                  <span>{d.getDate()}</span>
                  {lista.length > 0 && (
                    <span className="calendario-puntos">
                      {tipos.map((t) => <i key={t} style={{ background: ESTILO_TIPO[t].color }} />)}
                      <small>{lista.length}</small>
                    </span>
                  )}
                </button>
              )
            })}
          </div>
          <div className="agenda-leyenda">
            {Object.entries(ESTILO_TIPO).map(([t, e]) => (
              <span key={t}><i style={{ background: e.color }} /> {e.nombre}</span>
            ))}
          </div>
        </section>

        <section className="tarjeta">
          <h2>{dia === hoy ? 'Hoy' : fechaLegible(dia)}</h2>
          <Secciones lista={delDia} vacio="Nada agendado para este día." />
          <NuevoRecordatorio fecha={dia} />
        </section>
      </div>
    </>
  )
}

export function NuevoRecordatorio({ fecha, cobranzaId, alCrear }: {
  fecha?: string; cobranzaId?: string; alCrear?: () => void
}) {
  const qc = useQueryClient()
  const [abierto, setAbierto] = useState(false)
  const [tipo, setTipo] = useState<TipoRecordatorio>(cobranzaId ? 'llamada' : 'tarea')
  const [titulo, setTitulo] = useState('')
  const [dia, setDia] = useState(fecha ?? '')
  const [hora, setHora] = useState('')
  const [nota, setNota] = useState('')
  const [error, setError] = useState('')

  const crear = useMutation({
    mutationFn: () => api.post('/recordatorios', {
      tipo, titulo, fecha: dia || fecha, hora: hora || null, nota: nota || null, cobranza_id: cobranzaId ?? null,
    }),
    onSuccess: () => {
      setTitulo(''); setHora(''); setNota(''); setError(''); setAbierto(false)
      for (const queryKey of [['agenda'], ['agenda-hoy'], ['avisos']]) qc.invalidateQueries({ queryKey })
      alCrear?.()
    },
    onError: (err) => setError(mensajeDeError(err)),
  })

  if (!abierto) {
    return (
      <button className="btn btn-chico btn-secundario" onClick={() => { setDia(fecha ?? ''); setAbierto(true) }}>
        + Recordatorio
      </button>
    )
  }
  return (
    <form className="form-finanzas" onSubmit={(e: FormEvent) => { e.preventDefault(); crear.mutate() }}>
      <div>
        <span className="etiqueta-campo">Tipo</span>
        <div className="chips">
          {TIPOS_RECORDATORIO.map(([valor, nombre]) => (
            <button key={valor} type="button" className={`chip ${tipo === valor ? 'elegido' : ''}`}
              aria-pressed={tipo === valor} onClick={() => setTipo(valor)}>{nombre}</button>
          ))}
        </div>
      </div>
      <label>¿Qué hay que hacer? *
        <input value={titulo} onChange={(e) => setTitulo(e.target.value)} maxLength={200} required autoFocus
          placeholder="Ej. Llamar para confirmar la transferencia" />
      </label>
      <div className="fila">
        <label>Fecha *
          <input type="date" value={dia} onChange={(e) => setDia(e.target.value)} required />
        </label>
        <label>Hora
          <input type="time" value={hora} onChange={(e) => setHora(e.target.value)} />
        </label>
      </div>
      <label>Nota
        <textarea rows={2} value={nota} onChange={(e) => setNota(e.target.value)} />
      </label>
      {error && <div className="alerta-error">{error}</div>}
      <div className="fila">
        <button className="btn btn-primario" disabled={crear.isPending}>Guardar</button>
        <button type="button" className="btn btn-secundario" onClick={() => setAbierto(false)}>Cancelar</button>
      </div>
    </form>
  )
}

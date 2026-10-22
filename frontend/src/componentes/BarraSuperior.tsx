import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Link, NavLink, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Avisos as DatosAvisos, Cobranza, ItemAgenda } from '../api/tipos'
import { useAuth } from '../auth'
import Avisos from './Avisos'
import { EtiquetaEstado, Plata, enDias, fechaLocal, rutConPuntos } from './utiles'
import { ESTILO_TIPO } from '../paginas/Agenda'

// Barra de arriba: buscador de casos, la semana de la persona (sus
// pendientes día por día, se actualiza sola al registrar gestiones), los
// avisos y su perfil. El menú de módulos sigue en la barra lateral.

const NOMBRE_ROL: Record<string, string> = {
  admin: 'Administración', supervisor: 'Supervisión', operador: 'Ejecutivo/a', abogado: 'Abogado/a',
  procurador: 'Procurador/a', viewer: 'Consulta',
}
const DIAS_CORTOS = ['Dom', 'Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb']

/** Cierra un panel al hacer clic fuera o con Escape. */
function usePanel() {
  const [abierto, setAbierto] = useState(false)
  const caja = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!abierto) return
    const fuera = (e: MouseEvent) => { if (!caja.current?.contains(e.target as Node)) setAbierto(false) }
    const tecla = (e: KeyboardEvent) => { if (e.key === 'Escape') setAbierto(false) }
    document.addEventListener('mousedown', fuera)
    document.addEventListener('keydown', tecla)
    return () => { document.removeEventListener('mousedown', fuera); document.removeEventListener('keydown', tecla) }
  }, [abierto])
  return { abierto, setAbierto, caja }
}

export default function BarraSuperior({ avisos }: { avisos: DatosAvisos | undefined }) {
  return (
    <header className="barra-superior">
      <BuscadorGlobal />
      <div className="barra-superior-derecha">
        <MiSemana />
        <Avisos datos={avisos} />
        <MenuPerfil />
      </div>
    </header>
  )
}

function BuscadorGlobal() {
  const navegar = useNavigate()
  const [q, setQ] = useState('')
  const [buscado, setBuscado] = useState('')
  const { abierto, setAbierto, caja } = usePanel()

  useEffect(() => {
    const t = window.setTimeout(() => setBuscado(q.trim()), 250)
    return () => window.clearTimeout(t)
  }, [q])

  const { data, isFetching } = useQuery({
    queryKey: ['buscar-global', buscado],
    enabled: buscado.length >= 2,
    queryFn: async () => (await api.get<Cobranza[]>('/cobranzas/buscar', { params: { q: buscado, limit: 8 } })).data,
  })

  function ir(id: string) {
    setAbierto(false); setQ('')
    navegar(`/cobranzas/${id}`)
  }

  return (
    <div className="buscador-global" ref={caja}>
      <input type="search" value={q} placeholder="Buscar N° de cobranza, RUT o nombre del deudor…"
        aria-label="Buscar casos" onFocus={() => setAbierto(true)}
        onChange={(e) => { setQ(e.target.value); setAbierto(true) }}
        onKeyDown={(e) => { if (e.key === 'Enter' && data?.[0]) ir(data[0].id) }} />
      {abierto && buscado.length >= 2 && (
        <div className="buscador-resultados" role="listbox">
          {isFetching && !data ? <p className="suave">Buscando…</p> : data?.length === 0 ? (
            <p className="suave">Sin resultados para «{buscado}».</p>
          ) : data?.map((c) => (
            <button key={c.id} role="option" aria-selected={false} onClick={() => ir(c.id)}>
              <span><strong className="mono">N° {c.numero}</strong> {c.deudor_nombre}</span>
              <span className="suave">{rutConPuntos(c.deudor_rut)} · {c.cliente_nombre}</span>
              <span className="buscador-derecha"><Plata valor={c.monto_actual} /> <EtiquetaEstado estado={c.estado} /></span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function MiSemana() {
  const { abierto, setAbierto, caja } = usePanel()
  const hoy = fechaLocal()
  const hasta = enDias(6)
  const { data: items } = useQuery({
    queryKey: ['agenda', 'semana', hoy],
    queryFn: async () => (await api.get<ItemAgenda[]>('/agenda', { params: { desde: hoy, hasta } })).data,
    refetchInterval: 5 * 60 * 1000,
  })
  const dias = useMemo(() => Array.from({ length: 7 }, (_, i) => enDias(i)), [])
  const [elegido, setElegido] = useState(hoy)
  const porDia = useMemo(() => {
    const m = new Map<string, ItemAgenda[]>()
    for (const i of items ?? []) m.set(i.fecha, [...(m.get(i.fecha) ?? []), i])
    return m
  }, [items])
  const deHoy = porDia.get(hoy)?.length ?? 0
  const lista = porDia.get(elegido) ?? []

  return (
    <div className="mi-semana" ref={caja}>
      <button className="barra-boton" aria-expanded={abierto} onClick={() => setAbierto(!abierto)}>
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor"
          strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="4" width="18" height="18" rx="2" /><path d="M16 2v4M8 2v4M3 10h18" />
        </svg>
        <span>Mi semana</span>
        {deHoy > 0 && <span className="barra-contador">{deHoy} hoy</span>}
      </button>
      {abierto && (
        <div className="mi-semana-panel" role="dialog" aria-label="Mis pendientes de la semana">
          <div className="semana-dias">
            {dias.map((d) => {
              const [a, m, dd] = d.split('-').map(Number)
              const fecha = new Date(a, m - 1, dd)
              const n = porDia.get(d)?.length ?? 0
              return (
                <button key={d} className={`semana-dia${d === elegido ? ' elegido' : ''}${d === hoy ? ' hoy' : ''}`}
                  onClick={() => setElegido(d)}>
                  <span>{d === hoy ? 'Hoy' : DIAS_CORTOS[fecha.getDay()]}</span>
                  <strong>{dd}</strong>
                  <small>{n > 0 ? n : '·'}</small>
                </button>
              )
            })}
          </div>
          <ListaItems items={lista} vacio="Nada pendiente este día." alElegir={() => setAbierto(false)} />
          <div className="mi-semana-pie">
            <Link to="/agenda" onClick={() => setAbierto(false)}>Abrir la agenda completa</Link>
          </div>
        </div>
      )}
    </div>
  )
}

export function ListaItems({ items, vacio, alElegir }: { items: ItemAgenda[]; vacio: string; alElegir?: () => void }) {
  if (items.length === 0) return <p className="suave">{vacio}</p>
  return (
    <ul className="lista-pendientes">
      {items.map((i, n) => {
        const destino = i.causa_id ? `/judicial/causas/${i.causa_id}` : i.cobranza_id ? `/cobranzas/${i.cobranza_id}` : '/agenda'
        const contenido: ReactNode = (
          <>
            <span className="agenda-punto" style={{ background: ESTILO_TIPO[i.tipo].color }} aria-hidden="true" />
            <span className="lista-pendientes-texto">
              <span className={i.atrasado ? 'texto-rojo negrita' : 'negrita'}>{i.titulo}</span>
              <span className="suave">
                {ESTILO_TIPO[i.tipo].nombre}{i.hora && ` · ${i.hora.slice(0, 5)}`}
                {i.numero_cobranza && ` · N° ${i.numero_cobranza}`}
                {i.detalle && i.tipo !== 'contacto' && ` · ${i.detalle}`}
              </span>
            </span>
          </>
        )
        return <li key={n}><Link to={destino} onClick={alElegir}>{contenido}</Link></li>
      })}
    </ul>
  )
}

function MenuPerfil() {
  const { usuario, logout } = useAuth()
  const { abierto, setAbierto, caja } = usePanel()
  if (!usuario) return null
  const iniciales = usuario.nombre.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]?.toUpperCase()).join('')
  return (
    <div className="menu-perfil" ref={caja}>
      <button className="barra-boton perfil-boton" aria-expanded={abierto} onClick={() => setAbierto(!abierto)}>
        <span className="avatar" aria-hidden="true">{iniciales}</span>
        <span className="perfil-texto">
          <strong>{usuario.nombre}</strong>
          <small>{NOMBRE_ROL[usuario.rol] ?? usuario.rol}</small>
        </span>
      </button>
      {abierto && (
        <div className="perfil-panel" role="menu">
          <div className="perfil-cabecera">
            <strong>{usuario.nombre}</strong>
            <span className="suave">{usuario.email}</span>
            <span className="suave">{usuario.organizacion.nombre}</span>
          </div>
          <NavLink to="/mi-cuenta" role="menuitem" onClick={() => setAbierto(false)}>Mi cuenta y seguridad</NavLink>
          <NavLink to="/seguimiento" role="menuitem" onClick={() => setAbierto(false)}>Mi seguimiento</NavLink>
          <NavLink to="/agenda" role="menuitem" onClick={() => setAbierto(false)}>Mi agenda</NavLink>
          <button role="menuitem" onClick={() => logout()}>Cerrar sesión</button>
        </div>
      )}
    </div>
  )
}

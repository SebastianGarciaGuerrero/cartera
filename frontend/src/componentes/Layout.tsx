import { NavLink, Outlet, Navigate, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Empresa, ItemAgenda } from '../api/tipos'
import { LogoEmpresa } from './Logo'
import { useAuth } from '../auth'
import { MARCA } from '../marca'

// Estructura general: barra lateral de navegación + contenido.
// Si no hay sesión, redirige al login (esto protege todas las rutas hijas).
// Si la contraseña es temporal, obliga a pasar por Mi cuenta.

export default function Layout() {
  const { usuario, cargando, logout, esAdmin, etiqueta, tiene } = useAuth()
  const ubicacion = useLocation()

  const { data: empresa } = useQuery({
    queryKey: ['empresa'],
    enabled: Boolean(usuario),
    queryFn: async () => (await api.get<Empresa>('/empresa')).data,
    staleTime: 5 * 60 * 1000,
    retry: false,
  })

  // Contador de la agenda: lo de hoy más lo atrasado.
  const { data: agendaHoy } = useQuery({
    queryKey: ['agenda-hoy', 'yo'],
    enabled: Boolean(usuario) && usuario?.rol !== 'mandante',
    queryFn: async () => (await api.get<ItemAgenda[]>('/agenda/hoy')).data,
    refetchInterval: 5 * 60 * 1000,
  })

  if (cargando) return <div className="pantalla-carga">Cargando…</div>
  if (!usuario) return <Navigate to="/login" replace />
  if (usuario.debe_cambiar_password && ubicacion.pathname !== '/mi-cuenta') {
    return <Navigate to="/mi-cuenta" replace />
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="marca">
          <img className="marca-logo-img" src="/logo.svg" alt={MARCA.nombre} />
          <div>
            <div className="marca-nombre">{MARCA.nombre}</div>
            <div className="marca-sub">{usuario.organizacion.nombre}</div>
          </div>
        </div>
        <LogoEmpresa tieneLogo={empresa?.tiene_logo} version={empresa?.logo_actualizado_at}
          alt={usuario.organizacion.nombre} className="sidebar-logo-empresa" />

        <nav className="menu">
          <div className="menu-grupo">Gestión</div>
          <NavLink to="/agenda">
            Agenda
            {agendaHoy && agendaHoy.length > 0 && <span className="menu-contador">{agendaHoy.length}</span>}
          </NavLink>
          <NavLink to="/cobranzas" end>{etiqueta('cobranzas', 'Cobranzas')}</NavLink>
          <NavLink to="/deudores">{etiqueta('deudores', 'Deudores')}</NavLink>
          <NavLink to="/clientes">{etiqueta('clientes', 'Clientes')}</NavLink>
          {tiene('calculadora_369') && <NavLink to="/calculadora">Calculadora 3-6-9</NavLink>}

          <div className="menu-grupo">Ingresos</div>
          <NavLink to="/cobranzas/nueva">Ingreso de {etiqueta('cobranza', 'cobranza').toLowerCase()}</NavLink>
          <NavLink to="/abonos">Ingreso de abonos</NavLink>
          <NavLink to="/carga-masiva">Carga masiva</NavLink>

          <div className="menu-grupo">Reportes</div>
          <NavLink to="/panel">Panel</NavLink>
          <NavLink to="/informes">Informes</NavLink>
          {esAdmin && <NavLink to="/equipo">Equipo</NavLink>}

          {esAdmin && (
            <>
              <div className="menu-grupo">Administración</div>
              <NavLink to="/usuarios">Usuarios</NavLink>
              <NavLink to="/mi-empresa">Mi empresa</NavLink>
              <NavLink to="/configuracion">Configuración</NavLink>
            </>
          )}
        </nav>

        <div className="sidebar-pie">
          <NavLink to="/mi-cuenta" className="usuario-nombre">{usuario.nombre}</NavLink>
          <div className="usuario-email">{usuario.email}</div>
          <button className="btn btn-secundario btn-chico" onClick={() => logout()}>
            Cerrar sesión
          </button>
        </div>
      </aside>

      <main className="contenido">
        <Outlet />
        <footer className="pie-firma">
          Creado por{' '}
          <a href="https://sebastiangarcia.cl" target="_blank" rel="noreferrer">
            sebastiangarcia.cl
          </a>
        </footer>
      </main>
    </div>
  )
}

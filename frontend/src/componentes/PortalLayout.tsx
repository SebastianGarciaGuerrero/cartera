import { NavLink, Outlet, Navigate, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { AcuerdoPendiente, Empresa } from '../api/tipos'
import { LogoEmpresa } from './Logo'
import { useAuth } from '../auth'
import { MARCA } from '../marca'

// Estructura del portal de clientes (rol 'mandante'): el cliente del estudio
// ve solo su cartera, aprueba acuerdos y descarga sus informes. Tiene su
// propio menú; los usuarios internos que lleguen acá vuelven a la app.

export default function PortalLayout() {
  const { usuario, cargando, logout, tiene } = useAuth()
  const ubicacion = useLocation()
  const habilitado = usuario?.rol === 'mandante' && tiene('portal_mandantes')

  const { data: empresa } = useQuery({
    queryKey: ['empresa'],
    enabled: Boolean(usuario),
    queryFn: async () => (await api.get<Empresa>('/empresa')).data,
    staleTime: 5 * 60 * 1000,
    retry: false,
  })
  const { data: pendientes } = useQuery({
    queryKey: ['portal', 'pendientes'],
    enabled: habilitado,
    queryFn: async () => (await api.get<AcuerdoPendiente[]>('/portal/acuerdos/pendientes')).data,
  })

  if (cargando) return <div className="pantalla-carga">Cargando…</div>
  if (!usuario) return <Navigate to="/login" replace />
  if (usuario.rol !== 'mandante') return <Navigate to="/" replace />
  if (usuario.debe_cambiar_password && ubicacion.pathname !== '/portal/mi-cuenta') {
    return <Navigate to="/portal/mi-cuenta" replace />
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
          <div className="menu-grupo">Portal de clientes</div>
          <NavLink to="/portal" end>Resumen</NavLink>
          <NavLink to="/portal/acuerdos">
            Acuerdos por aprobar
            {pendientes && pendientes.length > 0 && <span className="menu-contador">{pendientes.length}</span>}
          </NavLink>
          <NavLink to="/portal/cartera">Cartera</NavLink>
          <NavLink to="/portal/informes">Informes</NavLink>
        </nav>

        <div className="sidebar-pie">
          <NavLink to="/portal/mi-cuenta" className="usuario-nombre">{usuario.nombre}</NavLink>
          <div className="usuario-email">{usuario.email}</div>
          <button className="btn btn-secundario btn-chico" onClick={() => logout()}>
            Cerrar sesión
          </button>
        </div>
      </aside>

      <main className="contenido">
        {habilitado || ubicacion.pathname === '/portal/mi-cuenta' ? <Outlet /> : (
          <section className="tarjeta">
            <h2>Portal no disponible</h2>
            <p>
              El portal de clientes no está activo en la cuenta de {usuario.organizacion.nombre}.
              Consulta con ellos para habilitarlo.
            </p>
          </section>
        )}
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

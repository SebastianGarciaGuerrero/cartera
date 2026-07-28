import { NavLink, Outlet, Navigate } from 'react-router-dom'
import { useAuth } from '../auth'
import { MARCA } from '../marca'

// Estructura general: barra lateral de navegación + contenido.
// Si no hay sesión, redirige al login (esto protege todas las rutas hijas).

export default function Layout() {
  const { usuario, cargando, logout } = useAuth()

  if (cargando) return <div className="pantalla-carga">Cargando…</div>
  if (!usuario) return <Navigate to="/login" replace />

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="marca">
          <img className="marca-logo-img" src="/logo.svg" alt={MARCA.nombre} />
          <div>
            <div className="marca-nombre">{MARCA.nombre}</div>
            <div className="marca-sub">{MARCA.eslogan}</div>
          </div>
        </div>

        <nav className="menu">
          <div className="menu-grupo">Gestión</div>
          <NavLink to="/cobranzas" end>Cobranzas</NavLink>
          <NavLink to="/deudores">Deudores</NavLink>

          <div className="menu-grupo">Ingresos</div>
          <NavLink to="/cobranzas/nueva">Ingreso de cobranza</NavLink>
          <NavLink to="/abonos">Ingreso de abonos</NavLink>
          <NavLink to="/carga-masiva">Carga masiva</NavLink>

          <div className="menu-grupo">Reportes</div>
          <NavLink to="/informes">Informes</NavLink>
          {usuario.rol_id === 1 && (
            <NavLink to="/equipo">Equipo</NavLink>
          )}

          {usuario.rol_id === 1 && (
            <>
              <div className="menu-grupo">Administración</div>
              <NavLink to="/usuarios">Usuarios</NavLink>
            </>
          )}
        </nav>

        <div className="sidebar-pie">
          <div className="usuario-nombre">{usuario.nombre}</div>
          <div className="usuario-email">{usuario.email}</div>
          <button className="btn btn-secundario btn-chico" onClick={logout}>
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

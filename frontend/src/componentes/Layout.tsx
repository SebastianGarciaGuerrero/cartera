import { Link, Outlet, Navigate, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Empresa } from '../api/tipos'
import { LogoEmpresa } from './Logo'
import { useAvisos } from './Avisos'
import BarraSuperior from './BarraSuperior'
import MenuLateral from './MenuLateral'
import RecordatorioDelDia from './RecordatorioDelDia'
import { useAuth } from '../auth'
import { MARCA } from '../marca'

// Estructura general: barra lateral con el menú de módulos, barra superior
// (buscador, la semana de la persona, avisos y perfil) y el contenido.
// Si no hay sesión, redirige al login (esto protege todas las rutas hijas).
// Si la contraseña es temporal, obliga a pasar por Mi cuenta. El rol
// mandante va a su propio portal (PortalLayout).

export default function Layout() {
  const { usuario, cargando } = useAuth()
  const ubicacion = useLocation()

  const { data: empresa } = useQuery({
    queryKey: ['empresa'],
    enabled: Boolean(usuario),
    queryFn: async () => (await api.get<Empresa>('/empresa')).data,
    staleTime: 5 * 60 * 1000,
    retry: false,
  })

  // Avisos (campana, inicio y recordatorio del día): lo atrasado, lo de hoy y lo de mañana.
  const { data: avisos } = useAvisos(Boolean(usuario) && usuario?.rol !== 'mandante')

  if (cargando) return <div className="pantalla-carga">Cargando…</div>
  if (!usuario) return <Navigate to="/login" replace />
  // Los clientes del estudio (rol mandante) usan el portal, no la app interna.
  if (usuario.rol === 'mandante') return <Navigate to="/portal" replace />
  if (usuario.debe_cambiar_password && ubicacion.pathname !== '/mi-cuenta') {
    return <Navigate to="/mi-cuenta" replace />
  }

  return (
    <div className="app">
      <aside className="sidebar">
        {/* El logo lleva al inicio desde cualquier pantalla. */}
        <Link to="/" className="marca-enlace" title="Ir al inicio">
          <div className="marca">
            <img className="marca-logo-img" src="/logo.svg" alt={MARCA.nombre} />
            <div>
              <div className="marca-nombre">{MARCA.nombre}</div>
              <div className="marca-sub">{usuario.organizacion.nombre}</div>
            </div>
          </div>
          <LogoEmpresa tieneLogo={empresa?.tiene_logo} version={empresa?.logo_actualizado_at}
            alt={usuario.organizacion.nombre} className="sidebar-logo-empresa" />
        </Link>

        {/* Por áreas y según el rol (ver MenuLateral); los permisos los aplica el servidor. */}
        <MenuLateral />
      </aside>

      <div className="principal">
        <BarraSuperior avisos={avisos} />
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
      <RecordatorioDelDia usuarioId={usuario.id} nombre={usuario.nombre} avisos={avisos} />
    </div>
  )
}

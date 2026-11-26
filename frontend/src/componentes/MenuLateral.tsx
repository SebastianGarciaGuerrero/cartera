import { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useAuth } from '../auth'
import { Icono } from './Iconos'
import type { NombreIcono } from './Iconos'

// Menú lateral por ÁREAS (extrajudicial, judicial, cargas, reportes,
// administración) y según el ROL: cada persona ve primero lo suyo.
//  - Ejecutiva: su trabajo y lo extrajudicial.
//  - Abogado/a y procurador/a: primero lo judicial; de lo extrajudicial solo
//    lo necesario para encontrar un caso.
//  - Supervisión y administración: todo (administración al final, plegada).
// Los grupos se pliegan; se recuerda cómo los dejó cada persona y el grupo
// de la pantalla actual siempre queda abierto. Lo que el rol no puede usar
// no aparece (los permisos los aplica igual el servidor).

interface Item {
  a: string
  nombre: string
  icono: NombreIcono
  /** ¿Está en esta pantalla? (por defecto: la ruta exacta o una sub-ruta). */
  activo?: (ruta: string, busqueda: string) => boolean
}

interface Grupo {
  clave: string
  nombre: string | null     // null = sin título (lo personal, arriba)
  items: Item[]
  plegadoInicial?: boolean
}

const CLAVE_GUARDADO = 'cartera.menu.'

function leerPlegados(usuarioId: string): Record<string, boolean> {
  try {
    return JSON.parse(localStorage.getItem(CLAVE_GUARDADO + usuarioId) ?? '{}')
  } catch {
    return {}
  }
}

function guardarPlegados(usuarioId: string, plegados: Record<string, boolean>) {
  try {
    localStorage.setItem(CLAVE_GUARDADO + usuarioId, JSON.stringify(plegados))
  } catch { /* sin almacenamiento: se usa el valor por defecto */ }
}

/** ¿La persona trabaja el área judicial? (el plan la incluye y su rol o permisos son judiciales). */
export function useVeJudicial(): boolean {
  const { usuario, esAdmin, tiene, puede } = useAuth()
  const rol = usuario?.rol ?? ''
  return tiene('judicial') && (esAdmin || ['supervisor', 'abogado', 'procurador'].includes(rol)
    || puede('judicial_causas') || puede('judicial_tramites'))
}

export function useMenu(): Grupo[] {
  const { usuario, esAdmin, etiqueta, tiene, puede } = useAuth()
  const rol = usuario?.rol ?? ''
  const judicialista = rol === 'abogado' || rol === 'procurador'
  const veJudicial = useVeJudicial()
  const totales = puede('ver_totales')

  const cartera: Item = {
    a: '/cobranzas', nombre: 'Cartera', icono: 'cartera',
    activo: (r) => r === '/cobranzas' || (r.startsWith('/cobranzas/') && r !== '/cobranzas/nueva'),
  }
  const deudores: Item = { a: '/deudores', nombre: etiqueta('deudores', 'Deudores'), icono: 'personas' }

  const miTrabajo: Grupo = {
    clave: 'mio', nombre: null, items: [
      { a: '/inicio', nombre: 'Inicio', icono: 'inicio' },
      { a: '/agenda', nombre: 'Agenda', icono: 'calendario' },
      { a: '/seguimiento', nombre: 'Mis números', icono: 'grafico' },
    ],
  }

  const extrajudicial: Grupo = {
    clave: 'extrajudicial', nombre: 'Extrajudicial', plegadoInicial: judicialista,
    items: judicialista ? [cartera, deudores] : [
      cartera, deudores,
      { a: '/abonos', nombre: 'Pagos y abonos', icono: 'billetera' },
      ...(tiene('calculadora_369') ? [{ a: '/calculadora', nombre: 'Calculadora 3-6-9', icono: 'calculadora' } as Item] : []),
    ],
  }

  const judicial: Grupo = {
    clave: 'judicial', nombre: 'Judicial', items: [
      { a: '/judicial', nombre: 'Causas y plazos', icono: 'balanza',
        activo: (r, b) => (r === '/judicial' && !b.includes('ver=demandar')) || r.startsWith('/judicial/causas') },
      ...(rol !== 'procurador' ? [{
        a: '/judicial?ver=demandar', nombre: 'Para demandar', icono: 'documento',
        activo: (r: string, b: string) => r === '/judicial' && b.includes('ver=demandar'),
      } as Item] : []),
      ...(totales ? [{ a: '/gastos', nombre: 'Gastos por cliente', icono: 'recibo' } as Item] : []),
    ],
  }

  const cargas: Grupo = {
    clave: 'cargas', nombre: 'Ingresos y cargas', items: [
      ...(puede('cobranzas_crear') ? [{ a: '/cobranzas/nueva', nombre: `Nueva ${etiqueta('cobranza', 'cobranza').toLowerCase()}`, icono: 'mas' } as Item] : []),
      ...(puede('carga_masiva') || puede('gestiones_masivas') ? [{ a: '/carga-masiva', nombre: 'Carga desde Excel', icono: 'subir' } as Item] : []),
    ],
  }

  const reportes: Grupo = {
    clave: 'reportes', nombre: 'Reportes', items: totales ? [
      { a: '/panel', nombre: 'Panel', icono: 'grafico' },
      { a: '/informes', nombre: 'Informes', icono: 'informe' },
      ...(esAdmin ? [{ a: '/equipo', nombre: 'Equipo', icono: 'personas' } as Item] : []),
    ] : [],
  }

  const administracion: Grupo = {
    clave: 'administracion', nombre: 'Administración', plegadoInicial: true, items: [
      ...(esAdmin || puede('clientes_editar') ? [{ a: '/clientes', nombre: etiqueta('clientes', 'Clientes'), icono: 'edificio' } as Item] : []),
      ...(esAdmin ? [
        { a: '/usuarios', nombre: 'Usuarios y permisos', icono: 'usuario' } as Item,
        { a: '/mi-empresa', nombre: 'Mi empresa', icono: 'maletin' } as Item,
        { a: '/configuracion', nombre: 'Configuración', icono: 'engranaje' } as Item,
      ] : []),
    ],
  }

  const orden = judicialista
    ? [miTrabajo, judicial, extrajudicial, cargas, reportes, administracion]
    : [miTrabajo, extrajudicial, ...(veJudicial ? [judicial] : []), cargas, reportes, administracion]
  return orden.filter((g) => g.items.length > 0)
}

export default function MenuLateral() {
  const { usuario } = useAuth()
  const { pathname, search } = useLocation()
  const grupos = useMenu()
  const [plegados, setPlegados] = useState<Record<string, boolean>>(() => leerPlegados(usuario?.id ?? ''))

  const esActivo = (item: Item) => item.activo
    ? item.activo(pathname, search)
    : pathname === item.a || pathname.startsWith(item.a + '/')

  function alternar(grupo: Grupo) {
    const actual = plegados[grupo.clave] ?? grupo.plegadoInicial ?? false
    const nuevo = { ...plegados, [grupo.clave]: !actual }
    setPlegados(nuevo)
    guardarPlegados(usuario?.id ?? '', nuevo)
  }

  return (
    <nav className="menu" aria-label="Menú principal">
      {grupos.map((g) => {
        const conActivo = g.items.some(esActivo)
        // El grupo de la pantalla actual siempre se ve abierto.
        const plegado = !conActivo && (plegados[g.clave] ?? g.plegadoInicial ?? false)
        return (
          <div key={g.clave} className={`menu-seccion${plegado ? ' plegada' : ''}`}>
            {g.nombre && (
              <button type="button" className="menu-grupo menu-grupo-boton" aria-expanded={!plegado}
                onClick={() => alternar(g)}>
                <span>{g.nombre}</span>
                <Icono nombre="flecha" className="menu-flecha" />
              </button>
            )}
            <div className="menu-items">
              {g.items.map((item) => (
                <Link key={item.a} to={item.a} className={esActivo(item) ? 'active' : undefined}
                  aria-current={esActivo(item) ? 'page' : undefined}>
                  <Icono nombre={item.icono} className="menu-icono" />
                  <span>{item.nombre}</span>
                </Link>
              ))}
            </div>
          </div>
        )
      })}
    </nav>
  )
}

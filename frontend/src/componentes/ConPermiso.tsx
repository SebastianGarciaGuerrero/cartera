import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth'

// Pantallas que no son para todos los roles (totales de la cartera, cargas
// masivas, ingreso de cobranzas…). Si el rol no tiene el permiso, lo dice
// en vez de mostrar errores.

export default function ConPermiso({ permiso, children }: { permiso: string | string[]; children: ReactNode }) {
  const { puede } = useAuth()
  const lista = Array.isArray(permiso) ? permiso : [permiso]
  if (lista.some((p) => puede(p))) return <>{children}</>
  return (
    <section className="tarjeta sin-permiso">
      <h2>Esta sección es de la administración</h2>
      <p className="suave">
        Tu rol no tiene acceso. Si lo necesitas, pídeselo a la administración
        (Usuarios → Roles y permisos).
      </p>
      <Link to="/inicio" className="btn btn-secundario">Volver al inicio</Link>
    </section>
  )
}

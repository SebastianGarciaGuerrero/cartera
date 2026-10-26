import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, mensajeDeError } from '../api/client'

// Roles y permisos: qué puede hacer cada rol además de trabajar sus casos
// (gestiones, acuerdos, abonos, gastos y recomendar la demanda, que son de
// todos). El administrador siempre lo puede todo.

interface VistaPermisos {
  permisos: Record<string, string>
  roles: Record<string, string[]>
  por_defecto: Record<string, string[]>
}

const NOMBRE_ROL: Record<string, string> = {
  admin: 'Administración', supervisor: 'Supervisión', abogado: 'Abogado/a', procurador: 'Procurador/a',
  operador: 'Ejecutivo/a', viewer: 'Consulta',
}

export default function RolesPermisos() {
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: ['permisos'],
    queryFn: async () => (await api.get<VistaPermisos>('/permisos')).data,
  })
  const [aviso, setAviso] = useState('')
  const guardar = useMutation({
    mutationFn: async (roles: Record<string, string[]>) => (await api.put<VistaPermisos>('/permisos', { roles })).data,
    onSuccess: (d) => { qc.setQueryData(['permisos'], d); setAviso('Permisos guardados. Cada persona los ve al volver a entrar.') },
    onError: (e) => setAviso(mensajeDeError(e)),
  })
  if (!data) return null
  const roles = Object.keys(data.roles)

  function alternar(rol: string, permiso: string) {
    const actuales = new Set(data!.roles[rol])
    if (actuales.has(permiso)) actuales.delete(permiso)
    else actuales.add(permiso)
    guardar.mutate({ [rol]: [...actuales] })
  }

  function restablecer(rol: string) {
    guardar.mutate({ [rol]: data!.por_defecto[rol] ?? [] })
  }

  return (
    <section className="tarjeta separado">
      <div className="tarjeta-cabecera">
        <h2>Roles y permisos</h2>
      </div>
      <p className="nota">
        Todos los roles (salvo Consulta) registran gestiones, promesas, acuerdos, abonos y gastos de sus casos, y
        pueden recomendar pasar una cobranza a demanda. Aquí se define lo demás.
      </p>
      <div className="tabla-desplazable">
        <table className="tabla tabla-permisos">
          <thead>
            <tr>
              <th>Permiso</th>
              {roles.map((r) => <th key={r} className="centro">{NOMBRE_ROL[r] ?? r}</th>)}
            </tr>
          </thead>
          <tbody>
            {Object.entries(data.permisos).map(([clave, nombre]) => (
              <tr key={clave}>
                <td>{nombre}</td>
                {roles.map((r) => (
                  <td key={r} className="centro">
                    <input type="checkbox" checked={data.roles[r].includes(clave)}
                      disabled={r === 'admin' || guardar.isPending}
                      aria-label={`${NOMBRE_ROL[r] ?? r}: ${nombre}`} onChange={() => alternar(r, clave)} />
                  </td>
                ))}
              </tr>
            ))}
            <tr>
              <td className="suave">Volver a lo recomendado</td>
              {roles.map((r) => (
                <td key={r} className="centro">
                  {r !== 'admin' && (
                    <button type="button" className="btn-texto" disabled={guardar.isPending}
                      onClick={() => restablecer(r)}>Restablecer</button>
                  )}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
      {aviso && <p className="nota">{aviso}</p>}
    </section>
  )
}

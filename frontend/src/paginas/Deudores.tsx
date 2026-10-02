import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Deudor, DeudorDetalle } from '../api/tipos'
import NuevoDeudor from '../componentes/NuevoDeudor'

const NOMBRE_CONTACTO: Record<string, string> = {
  telefono: 'Teléfono', celular: 'Celular', email: 'Email',
  whatsapp: 'WhatsApp', otro: 'Otro',
}

export default function Deudores() {
  const [busqueda, setBusqueda] = useState('')
  const [seleccionado, setSeleccionado] = useState<string | null>(null)

  // Búsqueda-primero: con 30.000+ deudores no listamos todo. La consulta solo
  // corre cuando hay texto (RUT o nombre); sin texto se muestra un aviso.
  const hayBusqueda = busqueda.trim().length >= 1
  const { data: deudores, isLoading } = useQuery({
    queryKey: ['deudores', busqueda],
    enabled: hayBusqueda,
    queryFn: async () =>
      (await api.get<Deudor[]>('/deudores/buscar', {
        params: { q: busqueda.trim() },
      })).data,
  })

  const { data: detalle } = useQuery({
    queryKey: ['deudor', seleccionado],
    enabled: seleccionado !== null,
    queryFn: async () =>
      (await api.get<DeudorDetalle>(`/deudores/${seleccionado}`)).data,
  })

  return (
    <>
      <header className="pagina-cabecera">
        <h1>Deudores</h1>
      </header>

      <div className="alta-zona">
        <NuevoDeudor />
      </div>

      <div className="filtros">
        <input
          className="buscador"
          placeholder="Buscar por RUT o nombre…"
          value={busqueda}
          onChange={(e) => setBusqueda(e.target.value)}
        />
      </div>

      <div className="ficha-grilla">
        <div>
          {!hayBusqueda ? (
            <div className="vacio-busqueda">
              Escribe un RUT o nombre para buscar un deudor.
            </div>
          ) : isLoading ? (
            <div className="pantalla-carga">Cargando…</div>
          ) : (
            <table className="tabla">
              <thead>
                <tr><th>RUT</th><th>Nombre</th><th>Comuna</th><th></th></tr>
              </thead>
              <tbody>
                {deudores?.map((d) => (
                  <tr
                    key={d.id}
                    className={seleccionado === d.id ? 'fila-activa' : ''}
                  >
                    <td className="mono">{d.rut}</td>
                    <td>
                      {d.nombre}
                      {d.en_boletin_comercial && <span className="etiqueta etiqueta-castigo">DICOM</span>}
                    </td>
                    <td>{d.comuna ?? '—'}</td>
                    <td>
                      <button
                        className="btn btn-chico btn-secundario"
                        onClick={() => setSeleccionado(d.id)}
                      >
                        Ver
                      </button>
                    </td>
                  </tr>
                ))}
                {deudores?.length === 0 && (
                  <tr><td colSpan={4} className="vacio">Sin resultados</td></tr>
                )}
              </tbody>
            </table>
          )}
        </div>

        {detalle && (
          <section className="tarjeta">
            <h2>{detalle.nombre}</h2>
            <dl className="datos">
              <dt>RUT</dt><dd className="mono">{detalle.rut}</dd>
              <dt>Tipo</dt><dd>{detalle.tipo === 'natural' ? 'Persona natural' : 'Persona jurídica'}</dd>
              <dt>Comuna</dt><dd>{detalle.comuna ?? '—'}</dd>
              <dt>Ciudad</dt><dd>{detalle.ciudad ?? '—'}</dd>
              <dt>DICOM</dt><dd>{detalle.en_boletin_comercial ? 'Sí' : 'No'}</dd>
            </dl>

            <h2>Contactos</h2>
            <ul className="lista-contactos">
              {detalle.contactos.filter((c) => c.activo).map((c) => (
                <li key={c.id}>
                  <span className="suave">{NOMBRE_CONTACTO[c.tipo] ?? c.tipo}</span>
                  <span className="mono">{c.valor}</span>
                </li>
              ))}
              {detalle.contactos.filter((c) => c.activo).length === 0 && (
                <li className="vacio">Sin contactos registrados</li>
              )}
            </ul>
            {detalle.observaciones && (
              <p className="observaciones">{detalle.observaciones}</p>
            )}
          </section>
        )}
      </div>
    </>
  )
}

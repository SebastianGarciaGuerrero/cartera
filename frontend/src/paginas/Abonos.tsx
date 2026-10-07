import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { Plata, EtiquetaEstado } from '../componentes/utiles'
import { FormPago } from '../componentes/Finanzas'
import type { Cobranza, CobranzaDetalle, Pago } from '../api/tipos'

// Ingreso de abonos (como la pantalla ABONOS del sistema original):
// 1. Buscar la cobranza por N°, ID cliente, RUT o nombre del deudor.
// 2. Ver la información obtenida (capital, abonado, saldo).
// 3. Registrar el abono con su desglose.

export default function Abonos() {
  const qc = useQueryClient()
  const [busqueda, setBusqueda] = useState('')
  const [seleccionada, setSeleccionada] = useState<string | null>(null)
  const [exito, setExito] = useState('')

  const { data: resultados } = useQuery({
    queryKey: ['buscar-cobranza-abono', busqueda],
    enabled: busqueda.trim().length >= 1 && seleccionada === null,
    queryFn: async () =>
      (await api.get<Cobranza[]>('/cobranzas/buscar', {
        params: { q: busqueda.trim(), limit: 8 },
      })).data,
  })

  const { data: cob } = useQuery({
    queryKey: ['cobranza', seleccionada],
    enabled: seleccionada !== null,
    queryFn: async () =>
      (await api.get<CobranzaDetalle>(`/cobranzas/${seleccionada}`)).data,
  })

  const { data: pagos } = useQuery({
    queryKey: ['pagos', seleccionada],
    enabled: seleccionada !== null,
    queryFn: async () =>
      (await api.get<Pago[]>('/pagos/', { params: { cobranza_id: seleccionada } })).data,
  })

  const totalAbonado = pagos?.reduce((s, p) => s + Number(p.monto), 0) ?? 0

  function alRegistrar() {
    setExito('Abono registrado correctamente. El recupero del mes ya lo incluye.')
    qc.invalidateQueries({ queryKey: ['cobranza', seleccionada] })
    qc.invalidateQueries({ queryKey: ['pagos', seleccionada] })
    qc.invalidateQueries({ queryKey: ['cobranzas'] })
  }

  return (
    <>
      <header className="pagina-cabecera">
        <h1>Ingreso de abonos</h1>
      </header>

      <div className="filtros">
        <input
          className="buscador"
          placeholder="Buscar cobranza por N°, ID cliente, RUT o nombre del deudor…"
          value={busqueda}
          onChange={(e) => { setBusqueda(e.target.value); setSeleccionada(null); setExito('') }}
          autoFocus
        />
      </div>

      {!seleccionada && resultados && (
        <table className="tabla">
          <thead>
            <tr>
              <th>N° Cobranza</th><th>ID cliente</th><th>Estado</th>
              <th className="der">Saldo</th><th></th>
            </tr>
          </thead>
          <tbody>
            {resultados.map((c) => (
              <tr key={c.id}>
                <td className="mono negrita">{c.numero}</td>
                <td className="mono">{c.id_externo ?? '—'}</td>
                <td><EtiquetaEstado estado={c.estado} /></td>
                <td className="der"><Plata valor={c.monto_actual} /></td>
                <td>
                  <button className="btn btn-chico btn-primario"
                    onClick={() => setSeleccionada(c.id)}>
                    Abonar
                  </button>
                </td>
              </tr>
            ))}
            {resultados.length === 0 && (
              <tr><td colSpan={5} className="vacio">Sin resultados</td></tr>
            )}
          </tbody>
        </table>
      )}

      {cob && (
        <div className="ficha-grilla">
          <section className="tarjeta">
            <h2>Información obtenida</h2>
            <dl className="datos">
              <dt>N° cobranza</dt>
              <dd className="mono negrita">{cob.numero}</dd>
              <dt>Deudor</dt>
              <dd>
                <strong>{cob.deudor?.nombre}</strong>
                <span className="mono suave"> {cob.deudor?.rut}</span>
              </dd>
              <dt>Cliente</dt>
              <dd>
                {cob.cliente?.nombre_fantasia ?? cob.cliente?.razon_social}
                {cob.filial && <span className="suave"> · {cob.filial.nombre}</span>}
              </dd>
              <dt>Capital original</dt>
              <dd><Plata valor={cob.monto_original} /></dd>
              <dt>Total abonado</dt>
              <dd><Plata valor={totalAbonado} /></dd>
              <dt>Saldo capital</dt>
              <dd className="negrita"><Plata valor={cob.monto_actual} /></dd>
              <dt>Estado</dt>
              <dd><EtiquetaEstado estado={cob.estado} /></dd>
            </dl>
            <p className="nota">
              <Link to={`/cobranzas/${cob.id}`}>Ver ficha completa →</Link>
            </p>
          </section>

          <section className="tarjeta">
            {exito ? (
              <>
                <div className="alerta-exito">{exito}</div>
                <div className="fila">
                  <Link className="btn btn-primario" to={`/cobranzas/${cob.id}`}>
                    Ver cobranza →
                  </Link>
                  <button className="btn btn-secundario" onClick={() => setExito('')}>
                    Registrar otro abono
                  </button>
                  <button className="btn btn-secundario"
                    onClick={() => { setSeleccionada(null); setBusqueda(''); setExito('') }}>
                    Buscar otra cobranza
                  </button>
                </div>
              </>
            ) : (
              <FormPago
                cobranzaId={cob.id}
                modalidad={cob.tipo}
                cuota={null}
                alTerminar={alRegistrar}
                alCancelar={() => { setSeleccionada(null); setBusqueda('') }}
              />
            )}
          </section>
        </div>
      )}
    </>
  )
}

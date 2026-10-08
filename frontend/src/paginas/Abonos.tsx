import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { useAuth } from '../auth'
import { EtiquetaEstado, fechaLegible, fechaLocal, Plata, rutConPuntos } from '../componentes/utiles'
import { FormPago } from '../componentes/Finanzas'
import type { PagoRegistrado } from '../componentes/Finanzas'
import type { Acuerdo, AcuerdoDetalle, Cobranza, CobranzaDetalle, Cuota, Pago } from '../api/tipos'

// Ingreso de abonos:
//  1. Buscar la cobranza (N°, ID del cliente, RUT o nombre del deudor).
//  2. Si tiene acuerdo vigente, elegir la cuota que se paga (por defecto la
//     más antigua pendiente); si no, abono libre.
//  3. Ingresar lo recibido: el desglose se arma solo (ver FormPago).
//  4. Queda un comprobante en pantalla con el nuevo saldo.

export default function Abonos() {
  const qc = useQueryClient()
  const { etiqueta } = useAuth()
  const [busqueda, setBusqueda] = useState('')
  const [seleccionada, setSeleccionada] = useState<string | null>(null)
  const [cuotaElegida, setCuotaElegida] = useState<string | 'libre' | null>(null)
  const [comprobante, setComprobante] = useState<PagoRegistrado | null>(null)

  const { data: resultados, isFetching } = useQuery({
    queryKey: ['buscar-cobranza-abono', busqueda],
    enabled: busqueda.trim().length >= 2 && seleccionada === null,
    queryFn: async () =>
      (await api.get<Cobranza[]>('/cobranzas/buscar', { params: { q: busqueda.trim(), limit: 10 } })).data,
  })

  const { data: cob } = useQuery({
    queryKey: ['cobranza', seleccionada],
    enabled: seleccionada !== null,
    queryFn: async () => (await api.get<CobranzaDetalle>(`/cobranzas/${seleccionada}`)).data,
  })
  const { data: acuerdos } = useQuery({
    queryKey: ['acuerdos', seleccionada],
    enabled: seleccionada !== null,
    queryFn: async () => (await api.get<Acuerdo[]>('/acuerdos/', { params: { cobranza_id: seleccionada } })).data,
  })
  const vigente = acuerdos?.find((a) => a.estado === 'vigente')
  const { data: acuerdo } = useQuery({
    queryKey: ['acuerdo', vigente?.id],
    enabled: Boolean(vigente),
    queryFn: async () => (await api.get<AcuerdoDetalle>(`/acuerdos/${vigente!.id}`)).data,
  })
  const { data: pagos } = useQuery({
    queryKey: ['pagos', seleccionada],
    enabled: seleccionada !== null,
    queryFn: async () => (await api.get<Pago[]>('/pagos/', { params: { cobranza_id: seleccionada } })).data,
  })

  const pendientes = (acuerdo?.cuotas ?? []).filter((c) => c.estado !== 'pagada')
  // Por defecto: la cuota pendiente más antigua (si hay acuerdo).
  const idCuota = cuotaElegida ?? (pendientes[0]?.id ?? 'libre')
  const cuota: Cuota | null = idCuota === 'libre' ? null : pendientes.find((c) => c.id === idCuota) ?? null
  const totalAbonado = pagos?.reduce((s, p) => s + Number(p.monto), 0) ?? 0
  const hoy = fechaLocal()

  function elegir(id: string) {
    setSeleccionada(id)
    setCuotaElegida(null)
    setComprobante(null)
  }
  function otraBusqueda() {
    setSeleccionada(null); setBusqueda(''); setComprobante(null); setCuotaElegida(null)
  }
  function alRegistrar(pago: PagoRegistrado) {
    setComprobante(pago)
    setCuotaElegida(null)
    for (const k of [['cobranza', seleccionada], ['pagos', seleccionada], ['acuerdos', seleccionada],
      ['acuerdo'], ['cobranzas'], ['agenda'], ['agenda-hoy'], ['panel']]) {
      qc.invalidateQueries({ queryKey: k })
    }
  }

  return (
    <>
      <header className="pagina-cabecera">
        <h1>Ingreso de abonos</h1>
      </header>

      {!seleccionada && (
        <>
          <div className="filtros">
            <input
              className="buscador"
              placeholder={`Buscar por N° de cobranza, ${etiqueta('id_externo', 'ID cliente')}, RUT o nombre del deudor…`}
              value={busqueda}
              onChange={(e) => setBusqueda(e.target.value)}
              autoFocus
            />
          </div>
          {busqueda.trim().length < 2 ? (
            <div className="vacio-busqueda">Escribe al menos 2 letras o números para buscar.</div>
          ) : (
            <div className="lista-resultados">
              {resultados?.map((c) => (
                <button key={c.id} className="resultado" onClick={() => elegir(c.id)}>
                  <span className="resultado-principal">
                    <strong>{c.deudor_nombre}</strong>
                  </span>
                  <span className="resultado-secundario">
                    <span className="mono">{rutConPuntos(c.deudor_rut)}</span> · N° {c.numero}{c.id_externo ? ` · ${etiqueta('id_externo', 'ID cliente')} ${c.id_externo}` : ''}
                    {c.cliente_nombre ? ` · ${c.cliente_nombre}` : ''}
                  </span>
                  <EtiquetaEstado estado={c.estado} />
                  <span className="resultado-monto"><Plata valor={c.monto_actual} /></span>
                </button>
              ))}
              {resultados?.length === 0 && !isFetching && <div className="vacio">Sin resultados para "{busqueda}".</div>}
            </div>
          )}
        </>
      )}

      {cob && (
        <>
          <section className="tarjeta resumen-cobranza">
            <div>
              <div className="suave">Cobranza N° {cob.numero} · {cob.cliente?.nombre_fantasia ?? cob.cliente?.razon_social}</div>
              <h2 className="resumen-titulo">{cob.deudor?.nombre} <span className="mono suave">{rutConPuntos(cob.deudor?.rut)}</span></h2>
              <EtiquetaEstado estado={cob.estado} />
            </div>
            <div className="resumen-cifras">
              <div><span className="suave">Deuda original</span><Plata valor={cob.monto_original} /></div>
              <div><span className="suave">Abonado</span><Plata valor={totalAbonado} /></div>
              <div><span className="suave">Saldo capital</span><strong><Plata valor={cob.monto_actual} /></strong></div>
            </div>
            <div className="acciones">
              <Link className="btn btn-chico btn-secundario" to={`/cobranzas/${cob.id}`}>Ver ficha</Link>
              <button className="btn btn-chico btn-secundario" onClick={otraBusqueda}>Otra cobranza</button>
            </div>
          </section>

          {comprobante ? (
            <section className="tarjeta comprobante">
              <div className="alerta-exito">
                {comprobante.cuota ? `Pago de la cuota ${comprobante.cuota}` : 'Abono'} registrado:{' '}
                <strong><Plata valor={comprobante.monto} /></strong> el {fechaLegible(comprobante.fecha)}.
              </div>
              <dl className="datos">
                <dt>Capital</dt><dd><Plata valor={comprobante.capital} /></dd>
                {comprobante.honorarios > 0 && (<><dt>Honorarios</dt><dd><Plata valor={comprobante.honorarios} /></dd></>)}
                {comprobante.intereses > 0 && (<><dt>Interés</dt><dd><Plata valor={comprobante.intereses} /></dd></>)}
                {comprobante.gastos > 0 && (<><dt>Gastos</dt><dd><Plata valor={comprobante.gastos} /></dd></>)}
                <dt>Nuevo saldo</dt><dd className="negrita"><Plata valor={cob.monto_actual} /></dd>
              </dl>
              <div className="acciones">
                <button className="btn btn-primario" onClick={() => setComprobante(null)}>Registrar otro pago</button>
                <button className="btn btn-secundario" onClick={otraBusqueda}>Buscar otra cobranza</button>
                <Link className="btn btn-secundario" to={`/cobranzas/${cob.id}`}>Ver cobranza</Link>
              </div>
            </section>
          ) : (
            <section className="tarjeta">
              {pendientes.length > 0 && (
                <>
                  <h2>¿Qué se paga?</h2>
                  <div className="opciones-cuota">
                    {pendientes.map((c) => (
                      <label key={c.id} className={`opcion ${idCuota === c.id ? 'elegida' : ''}`}>
                        <input type="radio" name="cuota" checked={idCuota === c.id} onChange={() => setCuotaElegida(c.id)} />
                        <span>Cuota {c.numero_cuota}/{acuerdo?.numero_cuotas}</span>
                        <span className={c.fecha_vencimiento < hoy ? 'texto-rojo' : 'suave'}>
                          vence {fechaLegible(c.fecha_vencimiento)}
                        </span>
                        <strong><Plata valor={Number(c.monto) - Number(c.monto_pagado)} /></strong>
                      </label>
                    ))}
                    <label className={`opcion ${idCuota === 'libre' ? 'elegida' : ''}`}>
                      <input type="radio" name="cuota" checked={idCuota === 'libre'} onChange={() => setCuotaElegida('libre')} />
                      <span>Abono libre</span>
                      <span className="suave">sin imputar a una cuota</span>
                    </label>
                  </div>
                </>
              )}
              <FormPago
                key={idCuota}
                cobranzaId={cob.id}
                modalidad={cob.tipo}
                cuota={cuota}
                alTerminar={alRegistrar}
                alCancelar={otraBusqueda}
              />
            </section>
          )}

          {pagos && pagos.length > 0 && (
            <section className="tarjeta">
              <h2>Últimos pagos</h2>
              <table className="tabla">
                <thead><tr><th>Fecha</th><th className="der">Monto</th><th className="der">Capital</th><th>Forma</th></tr></thead>
                <tbody>
                  {pagos.slice(0, 5).map((p) => (
                    <tr key={p.id}>
                      <td>{fechaLegible(p.fecha_pago)}</td>
                      <td className="der"><Plata valor={p.monto} /></td>
                      <td className="der"><Plata valor={p.capital} /></td>
                      <td>{p.forma_pago ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}
        </>
      )}
    </>
  )
}

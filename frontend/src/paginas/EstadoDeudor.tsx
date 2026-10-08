import { useState } from 'react'
import type { FormEvent } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api, mensajeDeError } from '../api/client'
import type { CuotaDeudor, DeudaDeudor, EstadoCuotaDeudor, EstadoDeudorPublico } from '../api/tipos'
import { clp, fechaLegible } from '../componentes/utiles'

// Portal del deudor: página pública que se abre con el enlace personal que
// envía el estudio (/estado#t=TOKEN). El token va en el fragmento (#), que
// el navegador nunca manda al servidor. Para ver algo hay que escribir el
// RUT; se pide de nuevo cada vez que se abre (no se guarda nada).

const NOMBRE_ESTADO: Record<string, string> = {
  activa: 'En cobranza', acuerdo_pago: 'Con convenio', judicial: 'Cobranza judicial', pagada: 'Pagada',
}
const CLASE_ESTADO: Record<string, string> = {
  activa: 'etiqueta-activa', acuerdo_pago: 'etiqueta-acuerdo_pago', judicial: 'etiqueta-judicial', pagada: 'etiqueta-pagada',
}
const NOMBRE_CUOTA: Record<EstadoCuotaDeudor, string> = {
  pagada: 'Pagada', pendiente: 'Pendiente', parcial: 'Pago parcial', atrasada: 'Atrasada',
}
const CLASE_CUOTA: Record<EstadoCuotaDeudor, string> = {
  pagada: 'etiqueta-pagada', pendiente: 'etiqueta-archivada', parcial: 'etiqueta-acuerdo_pago', atrasada: 'etiqueta-castigo',
}

function tokenDeLaUrl(): string {
  return new URLSearchParams(window.location.hash.replace(/^#/, '')).get('t') ?? ''
}

export default function EstadoDeudor() {
  const [token] = useState(tokenDeLaUrl)
  const [rut, setRut] = useState('')
  const consultar = useMutation({
    mutationFn: async () => (await api.post<EstadoDeudorPublico>('/publico/estado', { token, rut: rut.trim() })).data,
  })
  const estado = consultar.data

  return (
    <div className="publico">
      <header className="publico-cabecera">
        {estado?.estudio.logo
          ? <img src={estado.estudio.logo} alt={estado.estudio.nombre} className="publico-logo" />
          : <img src="/logo.svg" alt="" className="publico-logo publico-logo-generico" />}
        {estado && <span className="publico-estudio">{estado.estudio.nombre}</span>}
      </header>

      <main className="publico-contenido">
        {!token ? (
          <section className="tarjeta">
            <h1 className="publico-titulo">Enlace incompleto</h1>
            <p>Abra el enlace completo que recibió por WhatsApp o correo. Si no funciona, solicite uno nuevo a quien se lo envió.</p>
          </section>
        ) : !estado ? (
          <form className="tarjeta publico-acceso" onSubmit={(e: FormEvent) => { e.preventDefault(); consultar.mutate() }}>
            <h1 className="publico-titulo">Estado de su deuda</h1>
            <p className="suave">Para proteger su información, escriba su RUT.</p>
            <label>
              RUT
              <input value={rut} onChange={(e) => setRut(e.target.value)} placeholder="12.345.678-5"
                inputMode="text" autoComplete="off" autoFocus required maxLength={14} />
            </label>
            {consultar.error && <div className="alerta-error">{mensajeDeError(consultar.error)}</div>}
            <button className="btn btn-primario" disabled={consultar.isPending}>
              {consultar.isPending ? 'Consultando…' : 'Ver mi estado'}
            </button>
          </form>
        ) : <Estado e={estado} />}
      </main>

      <footer className="pie-firma">
        Creado por <a href="https://sebastiangarcia.cl" target="_blank" rel="noreferrer">sebastiangarcia.cl</a>
      </footer>
    </div>
  )
}

function Estado({ e }: { e: EstadoDeudorPublico }) {
  const nombre = e.nombre.split(' ')[0]
  const primerTelefono = e.estudio.telefonos?.split(/[,;/]/)[0].trim()
  return (
    <>
      <div>
        <h1 className="publico-titulo">Hola, {nombre.charAt(0) + nombre.slice(1).toLowerCase()}</h1>
        <p className="suave">Este es el estado de sus deudas al {fechaLegible(e.al)}.</p>
      </div>

      {e.deudas.length === 0 && (
        <section className="tarjeta">No tiene deudas en cobranza con {e.estudio.nombre}.</section>
      )}
      {e.deudas.map((d) => <Deuda key={d.numero} d={d} />)}

      <section className="tarjeta publico-contacto">
        <h2>¿Dudas o quiere pagar?</h2>
        <p>Comuníquese con {e.estudio.nombre}:</p>
        <ul>
          {primerTelefono && <li><a href={`tel:${primerTelefono.replace(/[^\d+]/g, '')}`}>{e.estudio.telefonos}</a></li>}
          {e.estudio.emails && <li><a href={`mailto:${e.estudio.emails.split(/[,;\s]/)[0]}`}>{e.estudio.emails}</a></li>}
          {e.estudio.horario && <li className="suave">{e.estudio.horario}</li>}
          {e.estudio.direccion && <li className="suave">{e.estudio.direccion}</li>}
        </ul>
      </section>

      <p className="nota">
        Si pagó hace poco, el pago puede tardar en verse aquí. Este enlace es personal: no lo comparta.
        Vence el {fechaLegible(e.enlace_vence)}.
      </p>
    </>
  )
}

function Deuda({ d }: { d: DeudaDeudor }) {
  const [copiado, setCopiado] = useState(false)
  const c = d.convenio
  return (
    <section className="tarjeta deuda-publica">
      <div className="deuda-publica-cabecera">
        <div>
          <strong>{d.acreedor}</strong>
          <div className="suave">Deuda N° {d.numero}</div>
        </div>
        <span className={`etiqueta ${CLASE_ESTADO[d.estado] ?? ''}`}>{NOMBRE_ESTADO[d.estado] ?? d.estado}</span>
      </div>

      {d.estado === 'pagada' ? (
        <p className="publico-ok">Esta deuda está pagada. Gracias.</p>
      ) : c ? (
        <Convenio c={c} />
      ) : (
        <>
          <dl className="datos">
            <dt>Capital adeudado</dt><dd className="negrita">{clp(Number(d.capital_pendiente))}</dd>
          </dl>
          <p className="nota">
            No incluye intereses ni gastos de cobranza. Comuníquese con nosotros para conocer el monto a pagar
            y las facilidades de pago.
          </p>
        </>
      )}

      {d.pagos.length > 0 && (
        <details>
          <summary>Sus pagos ({d.pagos.length})</summary>
          <ul className="publico-pagos">
            {d.pagos.map((p, i) => (
              <li key={i}><span>{fechaLegible(p.fecha)}</span><strong>{clp(Number(p.monto))}</strong></li>
            ))}
          </ul>
        </details>
      )}

      {d.estado !== 'pagada' && d.como_pagar && (
        <div className="publico-pago">
          <h3>Cómo pagar</h3>
          <p className="publico-datos-pago">{d.como_pagar}</p>
          <button className="btn btn-chico btn-secundario" onClick={() => {
            navigator.clipboard.writeText(d.como_pagar!); setCopiado(true)
          }}>{copiado ? 'Copiado ✓' : 'Copiar datos'}</button>
          <p className="nota">Indique la deuda N° {d.numero} y envíenos el comprobante para registrar su pago.</p>
        </div>
      )}
    </section>
  )
}

function Convenio({ c }: { c: NonNullable<DeudaDeudor['convenio']> }) {
  const pagado = Number(c.pagado)
  const total = pagado + Number(c.por_pagar)
  const pct = total > 0 ? Math.min(100, (pagado / total) * 100) : 0
  return (
    <>
      {c.cuotas_atrasadas > 0 && (
        <div className="publico-atraso">
          Tiene <strong>{c.cuotas_atrasadas} {c.cuotas_atrasadas === 1 ? 'cuota atrasada' : 'cuotas atrasadas'}</strong>{' '}
          por <strong>{clp(Number(c.monto_atrasado))}</strong>. Póngase al día para mantener su convenio.
        </div>
      )}
      {c.estado === 'cumplido' && <p className="publico-ok">Convenio cumplido.</p>}

      <div className="publico-progreso">
        <div className="publico-progreso-texto">
          <strong>{c.cuotas_pagadas} de {c.numero_cuotas} cuotas pagadas</strong>
          <span>{clp(pagado)} de {clp(total)}</span>
        </div>
        <div className="publico-barra" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
          <span style={{ width: `${pct}%` }} />
        </div>
      </div>

      {c.proxima && <Proxima cuota={c.proxima} />}

      <details>
        <summary>Ver todas las cuotas</summary>
        <table className="tabla publico-cuotas">
          <thead><tr><th>N°</th><th>Vence</th><th className="der">Monto</th><th>Estado</th></tr></thead>
          <tbody>
            {c.cuotas.map((q) => (
              <tr key={q.numero}>
                <td>{q.numero}</td>
                <td>{fechaLegible(q.vence)}</td>
                <td className="der">{clp(Number(q.monto))}</td>
                <td><span className={`etiqueta ${CLASE_CUOTA[q.estado]}`}>{NOMBRE_CUOTA[q.estado]}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </>
  )
}

function Proxima({ cuota }: { cuota: CuotaDeudor }) {
  const falta = Number(cuota.monto) - Number(cuota.pagado)
  return (
    <div className="publico-proxima">
      <span className="suave">Próxima cuota (N° {cuota.numero})</span>
      <strong>{clp(falta)}</strong>
      <span>vence el {fechaLegible(cuota.vence)}</span>
    </div>
  )
}

import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { useAuth } from '../auth'
import type { Seguimiento as Datos, Usuario } from '../api/tipos'
import { Plata, clp, fechaHoraLegible, fechaLegible } from '../componentes/utiles'

// Mi seguimiento: el panel de cada persona. Se actualiza solo con cada
// gestión, acuerdo o pago que registra (y cada minuto).

export default function Seguimiento() {
  const { usuario } = useAuth()
  const veOtros = usuario?.rol === 'admin' || usuario?.rol === 'supervisor'
  const [dias, setDias] = useState('30')
  const [persona, setPersona] = useState('')
  const { data: equipo } = useQuery({
    queryKey: ['usuarios'], enabled: usuario?.rol === 'admin',
    queryFn: async () => (await api.get<Usuario[]>('/usuarios/')).data,
  })
  const { data: s } = useQuery({
    queryKey: ['seguimiento', dias, persona],
    queryFn: async () => (await api.get<Datos>('/seguimiento', {
      params: { dias, ...(persona ? { usuario_id: persona } : {}) } })).data,
    refetchInterval: 60_000,
  })
  const p = s?.periodo
  const maximo = Math.max(1, ...(s?.por_dia.map((d) => d.gestiones) ?? [1]))

  return (
    <>
      <header className="pagina-cabecera">
        <h1>{persona && s ? `Seguimiento de ${s.usuario}` : 'Mi seguimiento'}</h1>
      </header>
      <div className="filtros">
        <select value={dias} onChange={(e) => setDias(e.target.value)}>
          <option value="7">Últimos 7 días</option>
          <option value="30">Últimos 30 días</option>
          <option value="90">Últimos 90 días</option>
        </select>
        {veOtros && equipo && (
          <select value={persona} onChange={(e) => setPersona(e.target.value)}>
            <option value="">Yo</option>
            {equipo.filter((u) => u.activo && u.id !== usuario?.id).map((u) => <option key={u.id} value={u.id}>{u.nombre}</option>)}
          </select>
        )}
      </div>

      {!s || !p ? <div className="pantalla-carga">Cargando…</div> : (
        <>
          <section className="kpis">
            <div className="kpi kpi-hero">
              <span className="kpi-titulo">Hoy</span>
              <span className="kpi-valor">{s.hoy.gestiones} gestiones</span>
              <span className="kpi-detalle">{s.hoy.contactos} contactos · {s.hoy.promesas} promesas · {s.hoy.acuerdos} acuerdos</span>
            </div>
            <div className="kpi">
              <span className="kpi-titulo">Gestiones del período</span>
              <span className="kpi-valor">{p.gestiones}</span>
              <span className="kpi-detalle">{p.contactos} contactos</span>
            </div>
            <div className="kpi">
              <span className="kpi-titulo">Promesas cumplidas</span>
              <span className="kpi-valor">{p.promesas_cumplidas} de {p.promesas}</span>
              <span className="kpi-detalle">{p.promesas_vencidas} vencidas sin pago</span>
            </div>
            <div className="kpi">
              <span className="kpi-titulo">Acuerdos</span>
              <span className="kpi-valor">{p.acuerdos}</span>
              <span className="kpi-detalle">{clp(Number(p.monto_acordado))} acordados</span>
            </div>
            <div className="kpi">
              <span className="kpi-titulo">Pagos registrados</span>
              <span className="kpi-valor">{clp(Number(p.monto_pagos))}</span>
              <span className="kpi-detalle">{p.pagos_registrados} pago(s)</span>
            </div>
            <div className="kpi">
              <span className="kpi-titulo">Cumplimiento de cuotas</span>
              <span className="kpi-valor">{p.cuotas_vencidas ? `${Math.round((p.cuotas_pagadas / p.cuotas_vencidas) * 100)} %` : '—'}</span>
              <span className="kpi-detalle">{p.cuotas_pagadas} de {p.cuotas_vencidas} que vencían</span>
            </div>
          </section>

          <section className="tarjeta">
            <h2>Gestiones por día</h2>
            <div className="barras-dia" role="img" aria-label="Gestiones por día">
              {s.por_dia.map((d) => (
                <div key={d.fecha} title={`${fechaLegible(d.fecha)}: ${d.gestiones} gestión(es)`}>
                  <span style={{ height: `${(d.gestiones / maximo) * 100}%` }} />
                </div>
              ))}
            </div>
            <p className="nota">{fechaLegible(s.desde)} al {fechaLegible(s.hasta)} · máximo {maximo} en un día</p>
          </section>

          <div className="panel-grilla">
            <section className="tarjeta">
              <h2>Mis acuerdos</h2>
              <p>{s.acuerdos_vigentes} vigentes · {s.acuerdos_al_dia} al día · por cobrar <Plata valor={s.por_cobrar} /></p>
              {s.atrasados.length > 0 && <h3 className="subtitulo">Atrasados ({s.atrasados.length})</h3>}
              <ul className="lista-simple">
                {s.atrasados.map((a) => (
                  <li key={a.cobranza_id}>
                    <Link to={`/cobranzas/${a.cobranza_id}`}>N° {a.numero} · {a.deudor}</Link>
                    <span className="texto-rojo">{a.cuotas_atrasadas} cuota(s) · {clp(Number(a.monto_atrasado))}</span>
                  </li>
                ))}
              </ul>
            </section>
            <section className="tarjeta">
              <h2>Cuotas de los próximos 7 días</h2>
              {s.proximas_cuotas.length === 0 && <p className="suave">No vence nada esta semana.</p>}
              <ul className="lista-simple">
                {s.proximas_cuotas.map((c) => (
                  <li key={`${c.cobranza_id}-${c.cuota}`}>
                    <Link to={`/cobranzas/${c.cobranza_id}`}>{c.deudor} · cuota {c.cuota}/{c.de}</Link>
                    <span>{fechaLegible(c.fecha)} · {clp(Number(c.monto))}</span>
                  </li>
                ))}
              </ul>
            </section>
            <section className="tarjeta">
              <h2>En qué se fue el tiempo</h2>
              <ul className="lista-simple">
                {s.por_tipo.map((t) => <li key={t.tipo}><span>{t.tipo}</span><strong>{t.cantidad}</strong></li>)}
                {s.por_tipo.length === 0 && <li className="suave">Sin gestiones en el período.</li>}
              </ul>
            </section>
            <section className="tarjeta">
              <h2>Últimas gestiones</h2>
              <ul className="lista-simple">
                {s.ultimas.map((g, i) => (
                  <li key={i}>
                    <Link to={`/cobranzas/${g.cobranza_id}`}>{g.deudor}: {g.tipo ?? 'Gestión'}</Link>
                    <span className="suave">{fechaHoraLegible(g.fecha)}</span>
                  </li>
                ))}
              </ul>
            </section>
          </div>
        </>
      )}
    </>
  )
}

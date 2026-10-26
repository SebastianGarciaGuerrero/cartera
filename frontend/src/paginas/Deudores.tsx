import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, mensajeDeError } from '../api/client'
import { useAuth } from '../auth'
import type { Cobranza, Contacto, DeudorBusqueda, DeudorDetalle, Gestion } from '../api/tipos'
import NuevoDeudor from '../componentes/NuevoDeudor'
import { EtiquetaEstado, EtiquetaReincidente, Plata, rutConPuntos } from '../componentes/utiles'
import { useCampos, VistaCamposExtra } from '../componentes/CamposExtra'
import { ResumenDeuda, usePagos } from '../componentes/HistorialPagos'
import LineaTiempo from '../componentes/LineaTiempo'
import { useConfirmacion } from '../componentes/ConfirmarGestion'

// Deudores: búsqueda por RUT o nombre (con miles de deudores no se lista
// todo) y una ficha: resumen de la deuda arriba y, en pestañas, sus
// cobranzas, sus gestiones, sus contactos y sus datos. Cada cobranza es una
// cuenta aparte: las abiertas y las anteriores se muestran separadas, cada
// gestión dice de qué cobranza es y un cambio de contacto queda en UNA.

const ABIERTAS = ['activa', 'acuerdo_pago', 'judicial']

const NOMBRE_CONTACTO: Record<string, string> = {
  telefono: 'Teléfono', celular: 'Celular', email: 'Correo', whatsapp: 'WhatsApp', otro: 'Otro',
}
// Como lo nombra la gestión que deja el servidor.
const CONTACTO_GESTION: Record<string, string> = {
  telefono: 'teléfono', celular: 'celular', email: 'correo', whatsapp: 'WhatsApp', otro: 'contacto',
}

function soloDigitos(v: string) {
  const d = v.replace(/\D/g, '')
  return d.length === 9 && d.startsWith('9') ? '56' + d : d.length === 8 ? '569' + d : d
}

export default function Deudores() {
  const { etiqueta } = useAuth()
  const [busqueda, setBusqueda] = useState('')
  const [seleccionado, setSeleccionado] = useState<string | null>(null)
  const hayBusqueda = busqueda.trim().length >= 2

  const { data: deudores, isFetching } = useQuery({
    queryKey: ['deudores', busqueda],
    enabled: hayBusqueda,
    queryFn: async () =>
      (await api.get<DeudorBusqueda[]>('/deudores/buscar', { params: { q: busqueda.trim(), limit: 30 } })).data,
  })

  return (
    <>
      <header className="pagina-cabecera">
        <h1>{etiqueta('deudores', 'Deudores')}</h1>
        <NuevoDeudor alCrear={() => setBusqueda('')} />
      </header>

      <div className="filtros">
        <input className="buscador" placeholder={`Buscar por RUT, nombre, N° de cobranza o ${etiqueta('id_externo', 'ID cliente')}…`} value={busqueda}
          onChange={(e) => setBusqueda(e.target.value)} autoFocus />
      </div>

      <div className="deudores-grilla">
        <div>
          {!hayBusqueda ? (
            <div className="vacio-busqueda">Escribe un RUT (con o sin puntos), parte del nombre, un N° de cobranza o un ID.</div>
          ) : (
            <div className="lista-resultados">
              {deudores?.map((d) => (
                <button key={d.id} className={`resultado ${seleccionado === d.id ? 'elegido' : ''}`}
                  onClick={() => setSeleccionado(d.id)}>
                  <span className="resultado-principal">
                    <strong>{d.nombre}</strong>
                  </span>
                  <span className="resultado-secundario">
                    <span className="mono">{rutConPuntos(d.rut)}</span> · {d.cobranzas_abiertas > 0
                      ? `${d.cobranzas_abiertas} ${d.cobranzas_abiertas === 1 ? 'cobranza abierta' : 'cobranzas abiertas'}`
                      : d.total_cobranzas > 0 ? 'Sin deudas abiertas' : 'Sin cobranzas'}
                    {d.comuna ? ` · ${d.comuna}` : ''}
                  </span>
                  {d.en_boletin_comercial && <span className="etiqueta etiqueta-castigo">DICOM</span>}
                  {d.reincidente && <EtiquetaReincidente cerradas={d.cobranzas_cerradas ?? 0} />}
                  <span className="resultado-monto">{d.saldo_abierto > 0 && <Plata valor={d.saldo_abierto} />}</span>
                </button>
              ))}
              {deudores?.length === 0 && !isFetching && <div className="vacio">Sin resultados para "{busqueda}".</div>}
            </div>
          )}
        </div>

        {seleccionado ? <FichaDeudor id={seleccionado} /> : hayBusqueda && deudores && deudores.length > 0 && (
          <div className="vacio-busqueda">Elige un deudor para ver su ficha.</div>
        )}
      </div>
    </>
  )
}

type PestanaFicha = 'cobranzas' | 'gestiones' | 'contactos' | 'datos'

function iniciales(nombre: string) {
  return nombre.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]).join('').toUpperCase()
}

function FichaDeudor({ id }: { id: string }) {
  const { etiqueta } = useAuth()
  const qc = useQueryClient()
  const [pestana, setPestana] = useState<PestanaFicha>('cobranzas')
  const { data: d } = useQuery({
    queryKey: ['deudor', id],
    queryFn: async () => (await api.get<DeudorDetalle>(`/deudores/${id}`)).data,
  })
  const { data: cobranzas } = useQuery({
    queryKey: ['cobranzas', 'deudor', id],
    queryFn: async () => (await api.get<Cobranza[]>('/cobranzas/', { params: { deudor_id: id, limit: 100 } })).data,
  })
  const { data: gestiones } = useQuery({
    queryKey: ['gestiones', 'deudor', id],
    enabled: pestana === 'gestiones',
    queryFn: async () => (await api.get<Gestion[]>('/gestiones/', { params: { deudor_id: id, limit: 200 } })).data,
  })
  const { data: campos } = useCampos('deudor')
  const { data: pagos } = usePagos({ deudor_id: id })
  const quitar = useMutation({
    mutationFn: ({ contactoId, cobranzaId }: { contactoId: string; cobranzaId?: string }) =>
      api.delete(`/deudores/contactos/${contactoId}`, { params: { cobranza_id: cobranzaId } }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['deudor', id] }); qc.invalidateQueries({ queryKey: ['gestiones'] }) },
  })
  const { pedir, modal } = useConfirmacion()
  const [filtroGestiones, setFiltroGestiones] = useState('')
  const [cuentaElegida, setCuentaElegida] = useState('')

  if (!d) return <section className="tarjeta"><div className="pantalla-carga">Cargando…</div></section>

  const contactos = d.contactos.filter((c) => c.activo)
  const porNumero = [...(cobranzas ?? [])].sort((a, b) => b.numero - a.numero)
  const abiertas = porNumero.filter((c) => ABIERTAS.includes(c.estado))
  const anteriores = porNumero.filter((c) => !ABIERTAS.includes(c.estado))
  // El resumen es de la deuda vigente (lo anterior es otra cuenta); sin deuda vigente, la historia.
  const vigentes = abiertas.length ? abiertas : porNumero
  const idsVigentes = new Set(vigentes.map((c) => c.id))
  const original = vigentes.reduce((s, c) => s + Number(c.monto_original), 0)
  const saldo = abiertas.reduce((s, c) => s + Number(c.monto_actual), 0)
  const pagosVigentes = pagos?.filter((p) => idsVigentes.has(p.cobranza_id))
  // Dónde queda la gestión de un cambio de contacto: en UNA cobranza.
  const cuenta = porNumero.find((c) => c.id === cuentaElegida) ?? abiertas[0] ?? porNumero[0]
  const gestionesVisibles = filtroGestiones ? gestiones?.filter((g) => g.cobranza_id === filtroGestiones) : gestiones
  const celular = contactos.find((c) => ['whatsapp', 'celular', 'telefono'].includes(c.tipo))
  const correo = contactos.find((c) => c.tipo === 'email')
  const numeros = new Map((cobranzas ?? []).map((c) => [c.id, c.numero]))
  const datos: [string, string | null | undefined][] = [
    ['Tipo', d.tipo === 'natural' ? 'Persona natural' : 'Persona jurídica'],
    ['Dirección', [d.direccion, d.departamento].filter(Boolean).join(', ') || null],
    ['Comuna', d.comuna], ['Ciudad', d.ciudad], ['Región', d.region],
    ['Empleador', [d.empleador, d.cargo].filter(Boolean).join(' · ') || null],
    ['Fono trabajo', d.telefono_trabajo],
    ['Contacto alternativo', d.contacto_alt_nombre
      ? `${d.contacto_alt_nombre}${d.contacto_alt_relacion ? ` (${d.contacto_alt_relacion})` : ''}${d.contacto_alt_telefono ? ` · ${d.contacto_alt_telefono}` : ''}`
      : null],
  ]
  const pestanas: [PestanaFicha, string, number | null][] = [
    ['cobranzas', etiqueta('cobranzas', 'Cobranzas'), cobranzas?.length ?? null],
    ['gestiones', 'Gestiones', gestiones?.length ?? null],
    ['contactos', 'Contactos', contactos.length],
    ['datos', 'Datos', null],
  ]

  return (
    <section className="tarjeta ficha-deudor">
      <header className="ficha-deudor-cabecera">
        <div className="ficha-deudor-identidad">
          <span className="iniciales" aria-hidden="true">{iniciales(d.nombre)}</span>
          <div>
            <h2>
              {d.nombre}
              {d.en_boletin_comercial && <span className="etiqueta etiqueta-castigo">DICOM</span>}
              {d.reincidente && <EtiquetaReincidente cerradas={d.cobranzas_cerradas ?? 0} />}
            </h2>
            <span className="ficha-deudor-meta">
              <span className="mono">{rutConPuntos(d.rut)}</span>
              {' · '}{d.tipo === 'natural' ? 'Persona natural' : 'Persona jurídica'}
              {d.comuna && ` · ${d.comuna}`}
            </span>
          </div>
        </div>
        <div className="acciones">
          {celular && <a className="btn btn-chico btn-secundario" href={`tel:${celular.valor.replace(/\s/g, '')}`}>Llamar</a>}
          {celular && <a className="btn btn-chico btn-secundario" href={`https://wa.me/${soloDigitos(celular.valor)}`} target="_blank" rel="noreferrer">WhatsApp</a>}
          {correo && <a className="btn btn-chico btn-secundario" href={`mailto:${correo.valor}`}>Correo</a>}
        </div>
      </header>

      <ResumenDeuda original={original} saldo={saldo} pagos={pagosVigentes} deudorId={d.id}
        enlaceAbonar={abiertas.length === 1 ? `/abonos?cobranza=${abiertas[0].id}` : abiertas.length > 1 ? `/abonos?q=${d.rut}` : undefined} />

      <nav className="pestanas pestanas-ficha" aria-label="Secciones de la ficha">
        {pestanas.map(([clave, nombre, cantidad]) => (
          <button key={clave} className={`pestana ${pestana === clave ? 'activa' : ''}`}
            aria-current={pestana === clave ? 'page' : undefined} onClick={() => setPestana(clave)}>
            {nombre}{cantidad != null && <span className="pestana-cantidad">{cantidad}</span>}
          </button>
        ))}
      </nav>

      {pestana === 'cobranzas' && (
        <>
          {cobranzas?.length === 0 && <p className="vacio">Sin cobranzas.</p>}
          {abiertas.length > 0 && (
            <>
              <h3 className="subtitulo">Abiertas ({abiertas.length})</h3>
              <ListaCobranzas lista={abiertas} />
            </>
          )}
          {anteriores.length > 0 && (
            <>
              <h3 className="subtitulo">Anteriores, cerradas ({anteriores.length})</h3>
              <ListaCobranzas lista={anteriores} />
            </>
          )}
        </>
      )}

      {pestana === 'gestiones' && (
        <>
          {porNumero.length > 1 && (
            <label className="filtro-cuenta">
              Ver las gestiones de
              <select value={filtroGestiones} onChange={(e) => setFiltroGestiones(e.target.value)}>
                <option value="">Todas sus cobranzas (cada una con su N°)</option>
                {porNumero.map((c) => (
                  <option key={c.id} value={c.id}>N° {c.numero} · {c.cliente_nombre} · {c.estado.replace('_', ' ')}</option>
                ))}
              </select>
            </label>
          )}
          {gestionesVisibles ? <LineaTiempo gestiones={gestionesVisibles} cobranzas={numeros} /> : <p className="suave">Cargando…</p>}
        </>
      )}

      {pestana === 'contactos' && (
        <>
          <ul className="lista-contactos">
            {contactos.map((c: Contacto) => (
              <li key={c.id}>
                <span className="suave">{NOMBRE_CONTACTO[c.tipo] ?? c.tipo}</span>
                <span className="mono">{c.valor}</span>
                <button className="btn-texto" title="Quitar contacto" onClick={() => pedir({
                  titulo: `Quitar ${c.valor}`, confirmar: 'Sí, quitar',
                  accion: () => quitar.mutateAsync({ contactoId: c.id, cobranzaId: cuenta?.id }),
                  gestion: `CONTACTO QUITADO: ${CONTACTO_GESTION[c.tipo] ?? c.tipo} ${c.valor}.`,
                  detalle: cuenta && <p className="suave">Queda en la cobranza N° {cuenta.numero}.</p>,
                })}>Quitar</button>
              </li>
            ))}
            {contactos.length === 0 && <li className="suave">Sin contactos registrados.</li>}
          </ul>
          {abiertas.length > 1 ? (
            <label className="filtro-cuenta separado">
              Los cambios de contacto quedan como gestión en la cobranza
              <select value={cuenta?.id ?? ''} onChange={(e) => setCuentaElegida(e.target.value)}>
                {abiertas.map((c) => <option key={c.id} value={c.id}>N° {c.numero} · {c.cliente_nombre}</option>)}
              </select>
            </label>
          ) : cuenta && (
            <p className="nota separado">Los cambios de contacto quedan como gestión en la cobranza N° {cuenta.numero}.</p>
          )}
          <div className="separado"><NuevoContacto deudorId={d.id} cuenta={cuenta} /></div>
          {modal}
        </>
      )}

      {pestana === 'datos' && (
        <>
          <dl className="datos">
            {datos.filter(([, v]) => v).map(([k, v]) => (
              <div key={k} className="contents"><dt>{k}</dt><dd>{v}</dd></div>
            ))}
            <VistaCamposExtra campos={campos} valores={d.datos_extra} />
          </dl>
          {d.observaciones && <p className="observaciones">{d.observaciones}</p>}
        </>
      )}
    </section>
  )
}

function ListaCobranzas({ lista }: { lista: Cobranza[] }) {
  return (
    <ul className="lista-cobranzas">
      {lista.map((c) => (
        <li key={c.id}>
          <Link to={`/cobranzas/${c.id}`} className="negrita">N° {c.numero}{c.id_externo && <span className="mono suave"> · {c.id_externo}</span>}</Link>
          <strong><Plata valor={c.monto_actual} /></strong>
          <span className="suave">{c.cliente_nombre}</span>
          <span className="lista-cobranzas-estado">
            <EtiquetaEstado estado={c.estado} />
            {ABIERTAS.includes(c.estado) && (
              <Link className="btn btn-chico btn-secundario" to={`/abonos?cobranza=${c.id}`}>Abonar</Link>
            )}
          </span>
        </li>
      ))}
    </ul>
  )
}

function NuevoContacto({ deudorId, cuenta }: { deudorId: string; cuenta?: Cobranza }) {
  const qc = useQueryClient()
  const [abierto, setAbierto] = useState(false)
  const [tipo, setTipo] = useState('celular')
  const [valor, setValor] = useState('')
  const [error, setError] = useState('')
  const agregar = useMutation({
    mutationFn: () => api.post(`/deudores/${deudorId}/contactos`, { tipo, valor: valor.trim() },
      { params: { cobranza_id: cuenta?.id } }),
    onSuccess: () => {
      setValor(''); setAbierto(false); setError('')
      qc.invalidateQueries({ queryKey: ['deudor', deudorId] }); qc.invalidateQueries({ queryKey: ['gestiones'] })
    },
    onError: (err) => setError(mensajeDeError(err)),
  })
  const { pedir, modal } = useConfirmacion()
  if (!abierto) {
    return <button className="btn btn-chico btn-secundario" onClick={() => setAbierto(true)}>+ Contacto</button>
  }
  return (
    <form className="fila" onSubmit={(e: FormEvent) => {
      e.preventDefault()
      pedir({ titulo: 'Agregar contacto', confirmar: 'Sí, agregar', accion: () => agregar.mutateAsync(),
        gestion: `CONTACTO AGREGADO: ${CONTACTO_GESTION[tipo] ?? tipo} ${valor.trim()}.`,
        detalle: cuenta && <p className="suave">Queda en la cobranza N° {cuenta.numero}.</p> })
    }}>
      {modal}
      <select value={tipo} onChange={(e) => setTipo(e.target.value)}>
        {Object.entries(NOMBRE_CONTACTO).map(([v, n]) => <option key={v} value={v}>{n}</option>)}
      </select>
      <input value={valor} onChange={(e) => setValor(e.target.value)} required autoFocus
        placeholder={tipo === 'email' ? 'correo@ejemplo.cl' : '+56 9 1234 5678'} />
      <button className="btn btn-chico btn-primario" disabled={agregar.isPending}>Agregar</button>
      <button type="button" className="btn btn-chico btn-secundario" onClick={() => setAbierto(false)}>Cancelar</button>
      {error && <span className="alerta-error">{error}</span>}
    </form>
  )
}

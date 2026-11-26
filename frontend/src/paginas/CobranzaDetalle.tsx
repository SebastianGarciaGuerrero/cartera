import { Fragment, useState } from 'react'
import { useParams, Link, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, descargarArchivo, mensajeDeError } from '../api/client'
import { refrescarCaso } from '../api/refrescar'
import type { CobranzaDetalle as Ficha, DeudorDetalle, Gestion } from '../api/tipos'
import {
  EtiquetaEstado, EtiquetaReincidente, NOMBRE_CONTACTO, NOMBRE_DOCUMENTO, Plata, fechaLegible, fechaLocal, rutConPuntos, soloDigitos,
} from '../componentes/utiles'
import Finanzas from '../componentes/Finanzas'
import { useCampos, VistaCamposExtra } from '../componentes/CamposExtra'
import { useAuth } from '../auth'
import MensajePago from '../componentes/MensajePago'
import EnlaceDeudor from '../componentes/EnlaceDeudor'
import RegistrarGestion from '../componentes/RegistrarGestion'
import type { ResultadoGestion } from '../componentes/RegistrarGestion'
import { NuevoRecordatorio } from './Agenda'
import CicloVida, { DetalleCiclo, useCiclo } from '../componentes/CicloVida'
import { ResumenDeuda, usePagos } from '../componentes/HistorialPagos'
import Documentos from '../componentes/Documentos'
import LineaTiempo from '../componentes/LineaTiempo'

// La pantalla más usada del sistema: la ficha de una cobranza.
//  - Arriba, siempre a la vista: quién debe, a quién, cuánto, en qué etapa
//    está y cómo contactarlo (llamar, WhatsApp, correo, mensaje de pago).
//  - Debajo, en pestañas: Gestiones (registrar la siguiente y el historial),
//    Acuerdo y pagos, Datos del caso, Documentos y Judicial.
// Los pagos se registran por un solo camino: "Registrar pago" (arriba) o
// "Pagar" en una cuota abren el mismo formulario, que deja su gestión.
// La pestaña va en la dirección (?ver=pagos), así un aviso o la agenda
// pueden abrir la ficha directo donde corresponde.

export type PestanaCobranza = 'gestiones' | 'pagos' | 'datos' | 'documentos' | 'judicial'
const PESTANAS: PestanaCobranza[] = ['gestiones', 'pagos', 'datos', 'documentos', 'judicial']

export default function CobranzaDetalle() {
  const { id } = useParams()
  const { usuario, etiqueta, tiene, puede } = useAuth()
  const [params, setParams] = useSearchParams()
  const [mensaje, setMensaje] = useState(false)
  const [enlace, setEnlace] = useState(false)

  const { data: cob, isLoading } = useQuery({
    queryKey: ['cobranza', id],
    queryFn: async () => (await api.get<Ficha>(`/cobranzas/${id}`)).data,
  })

  // Contactos y si es reincidente (esta cobranza es una cuenta aparte de las anteriores).
  const { data: deudor } = useQuery({
    queryKey: ['deudor', cob?.deudor?.id],
    enabled: Boolean(cob?.deudor?.id),
    queryFn: async () => (await api.get<DeudorDetalle>(`/deudores/${cob!.deudor!.id}`)).data,
  })

  const { data: gestiones } = useQuery({
    queryKey: ['gestiones', id],
    queryFn: async () =>
      (await api.get<Gestion[]>('/gestiones/', { params: { cobranza_id: id } })).data,
  })
  const { data: pagos } = usePagos({ cobranza_id: id })
  const { data: ciclo } = useCiclo(id ?? '')
  const { data: campos } = useCampos('cobranza', cob?.cliente_id)

  // Resultado y cuota elegidos en "Registrar gestión" (la pestaña de pagos puede abrirlo).
  const [resultado, setResultado] = useState<ResultadoGestion>('gestion')
  const [cuota, setCuota] = useState('')

  const conJudicial = tiene('judicial')
  const judicialista = usuario?.rol === 'abogado' || usuario?.rol === 'procurador'
  const pedida = params.get('ver') as PestanaCobranza | null
  const pestana: PestanaCobranza = pedida && PESTANAS.includes(pedida) && (pedida !== 'judicial' || conJudicial)
    ? pedida : judicialista && conJudicial ? 'judicial' : 'gestiones'

  function irA(p: PestanaCobranza) {
    setParams((actual) => {
      const nuevos = new URLSearchParams(actual)
      nuevos.set('ver', p)
      return nuevos
    }, { replace: true })
  }
  function abrirFormulario(r: ResultadoGestion, cuotaId = '') {
    setResultado(r)
    setCuota(cuotaId)
    irA('gestiones')
    window.setTimeout(() => {
      document.getElementById('registrar-gestion')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }, 0)
  }

  if (isLoading || !cob) return <div className="pantalla-carga">Cargando ficha…</div>

  const contactos = (deudor?.contactos ?? []).filter((c) => c.activo)
  const celular = contactos.find((c) => ['celular', 'whatsapp'].includes(c.tipo))
    ?? contactos.find((c) => c.tipo === 'telefono')
  const correo = contactos.find((c) => c.tipo === 'email')
  const pagosVigentes = (pagos ?? []).filter((p) => !p.anulado_at).length

  const pestanas: [PestanaCobranza, string, number | null][] = [
    ['gestiones', 'Gestiones', gestiones?.length ?? null],
    ['pagos', 'Acuerdo y pagos', pagosVigentes || null],
    ['datos', 'Datos del caso', null],
    ['documentos', 'Documentos', null],
    ...(conJudicial ? [['judicial', 'Judicial', ciclo?.causas.length || null] as [PestanaCobranza, string, number | null]] : []),
  ]

  return (
    <>
      <header className="ficha-caso">
        <Link to="/cobranzas" className="volver">← Cartera</Link>
        <div className="ficha-caso-fila">
          <div className="ficha-caso-identidad">
            <h1>
              <span className="ficha-caso-numero">N° {cob.numero}</span>
              {cob.deudor?.nombre ?? 'Sin deudor'}
              <EtiquetaEstado estado={cob.estado} />
              {cob.deudor?.en_boletin_comercial && <span className="etiqueta etiqueta-castigo">DICOM</span>}
              {deudor?.reincidente && <EtiquetaReincidente cerradas={deudor.cobranzas_cerradas ?? 0} />}
            </h1>
            <div className="ficha-caso-meta">
              {cob.deudor && (
                <Link to={`/deudores?id=${cob.deudor.id}`} title="Ver todas sus cobranzas y contactos" className="mono">
                  {rutConPuntos(cob.deudor.rut)}
                </Link>
              )}
              <span>{cob.cliente?.nombre_fantasia ?? cob.cliente?.razon_social ?? '—'}{cob.filial && ` · ${cob.filial.nombre}`}</span>
              {cob.id_externo && <span>{etiqueta('id_externo', 'ID cliente')} <span className="mono">{cob.id_externo}</span></span>}
              <span>Ejecutivo: {cob.ejecutivo_nombre ?? 'sin asignar'}</span>
            </div>
          </div>
          <div className="ficha-caso-contacto">
            {celular && <a className="btn btn-chico btn-secundario" href={`tel:${celular.valor.replace(/[^\d+]/g, '')}`}>Llamar</a>}
            {celular && (
              <a className="btn btn-chico btn-secundario" href={`https://wa.me/${soloDigitos(celular.valor)}`} target="_blank" rel="noreferrer">
                WhatsApp
              </a>
            )}
            {correo && <a className="btn btn-chico btn-secundario" href={`mailto:${correo.valor}`}>Correo</a>}
            {tiene('mensaje_pago') && (
              <button className="btn btn-chico btn-primario" onClick={() => setMensaje(true)}>Mensaje de pago</button>
            )}
            {!celular && !correo && deudor && <span className="nota">Sin teléfono ni correo registrados.</span>}
          </div>
        </div>
      </header>

      <CicloVida cobranza={cob} />
      <ResumenDeuda original={Number(cob.monto_original)} saldo={Number(cob.monto_actual)} pagos={pagos}
        cobranzaId={cob.id} nombreAbonar="Registrar pago" alAbonar={() => abrirFormulario('pago')}
        alVerHistorial={() => irA('pagos')} />

      <nav className="pestanas pestanas-ficha" aria-label="Secciones de la cobranza">
        {pestanas.map(([clave, nombre, cantidad]) => (
          <button key={clave} className={`pestana ${pestana === clave ? 'activa' : ''}`}
            aria-current={pestana === clave ? 'page' : undefined} onClick={() => irA(clave)}>
            {nombre}{cantidad != null && <span className="pestana-cantidad">{cantidad}</span>}
          </button>
        ))}
      </nav>

      {pestana === 'gestiones' && (
        <div className="ficha-gestiones">
          <section className="tarjeta">
            <RegistrarGestion cobranza={cob} resultado={resultado} setResultado={setResultado}
              cuota={cuota} setCuota={setCuota} />
            <div className="separado">
              <NuevoRecordatorio cobranzaId={cob.id} fecha={fechaLocal()} />
            </div>
          </section>
          <section className="tarjeta">
            <h2>Historial ({gestiones?.length ?? 0})</h2>
            <LineaTiempo gestiones={gestiones} />
          </section>
        </div>
      )}

      {pestana === 'pagos' && (
        <Finanzas cobranza={cob} alPedirAcuerdo={() => abrirFormulario('acuerdo')}
          alPagar={(cuotaId) => abrirFormulario('pago', cuotaId)} />
      )}

      {pestana === 'datos' && (
        <div className="ficha-grilla">
          <section className="tarjeta">
            <h2>Datos del caso</h2>
            <dl className="datos">
              <dt>N° cobranza</dt>
              <dd className="mono negrita">{cob.numero}</dd>
              <dt>Deudor</dt>
              <dd>
                <strong>{cob.deudor?.nombre ?? '—'}</strong>
                <span className="mono suave"> {cob.deudor?.rut}</span>
              </dd>
              {cob.terceros.map((t) => (
                <Fragment key={`${t.tercero_id}-${t.rol}`}>
                  <dt className="capitalizar">{t.rol.replace('_', ' ')}</dt>
                  <dd>{t.nombre}{t.rut && <span className="mono suave"> {t.rut}</span>}</dd>
                </Fragment>
              ))}
              <dt>{etiqueta('cliente', 'Cliente')}</dt>
              <dd>
                {cob.cliente?.nombre_fantasia ?? cob.cliente?.razon_social ?? '—'}
                {cob.filial && <span className="suave"> · {cob.filial.nombre}</span>}
              </dd>
              <dt>Ejecutivo</dt>
              <dd>
                {puede('cartera_gestionar')
                  ? <SelectorEjecutivo cobranzaId={cob.id} actual={cob.ejecutivo_id ?? null} />
                  : (cob.ejecutivo_nombre ?? <span className="suave">Sin asignar</span>)}
              </dd>
              <dt>{etiqueta('id_externo', 'ID cliente')}</dt>
              <dd className="mono">{cob.id_externo ?? '—'}</dd>
              <dt>Documento</dt>
              <dd>
                {NOMBRE_DOCUMENTO[cob.tipo_documento] ?? cob.tipo_documento}
                {cob.numero_documento && <span className="mono suave"> N° {cob.numero_documento}</span>}
              </dd>
              {cob.fecha_vencimiento_documento && (
                <>
                  <dt>Vencimiento</dt>
                  <dd>{fechaLegible(cob.fecha_vencimiento_documento)}</dd>
                </>
              )}
              <dt>Deuda original</dt>
              <dd><Plata valor={cob.monto_original} /></dd>
              <dt>Saldo actual</dt>
              <dd className="negrita"><Plata valor={cob.monto_actual} /></dd>
              <dt>Fecha de ingreso</dt>
              <dd>{fechaLegible(cob.fecha_ingreso)}</dd>
              <dt>Tipo</dt>
              <dd className="capitalizar">{cob.tipo}</dd>
              <VistaCamposExtra campos={campos} valores={cob.datos_extra} />
            </dl>
            {cob.observaciones && <p className="observaciones">{cob.observaciones}</p>}
          </section>

          <section className="tarjeta">
            <h2>Contactos</h2>
            {contactos.length === 0 ? <p className="suave">Sin contactos registrados.</p> : (
              <ul className="lista-contactos">
                {contactos.map((c) => (
                  <li key={c.id}><span className="suave">{NOMBRE_CONTACTO[c.tipo] ?? c.tipo}</span><span className="mono">{c.valor}</span></li>
                ))}
              </ul>
            )}
            {cob.deudor && (
              <p className="nota">
                Para agregar o quitar contactos, abre la <Link to={`/deudores?id=${cob.deudor.id}`}>ficha del deudor</Link>.
              </p>
            )}
            {tiene('portal_deudor') && cob.deudor && (
              <div className="separado">
                <h2>Portal del deudor</h2>
                <p className="suave">Un enlace para que el deudor vea su deuda, su acuerdo y sus cuotas.</p>
                <button className="btn btn-secundario" onClick={() => setEnlace(true)}>Enlace para el deudor</button>
              </div>
            )}
          </section>
        </div>
      )}

      {pestana === 'documentos' && (
        <>
          <section className="tarjeta documentos-generar">
            <h2>Generar documento</h2>
            <div className="acciones">
              <button className="btn btn-secundario" onClick={() => descargarArchivo(`/documentos/informe-gestiones/${cob.id}`)}>
                Informe de gestiones (Word)
              </button>
              <button className="btn btn-secundario" onClick={() => descargarArchivo(`/documentos/estado-cuenta/${cob.id}`)}>
                Estado de cuenta (Word)
              </button>
              {tiene('calculadora_369') && (
                <Link className="btn btn-secundario" to={`/calculadora?cobranza=${cob.id}`}>Calculadora / acuerdo 3-6-9</Link>
              )}
            </div>
            <p className="nota">El acuerdo o avenimiento en Word está en la pestaña "Acuerdo y pagos".</p>
          </section>
          <Documentos cobranzaId={cob.id} />
        </>
      )}

      {pestana === 'judicial' && conJudicial && <DetalleCiclo cobranzaId={cob.id} />}

      {mensaje && <MensajePago cobranzaId={cob.id} alCerrar={() => setMensaje(false)} />}
      {enlace && cob.deudor && (
        <EnlaceDeudor deudorId={cob.deudor.id} deudorNombre={cob.deudor.nombre} cobranzaId={cob.id}
          alCerrar={() => setEnlace(false)} />
      )}
    </>
  )
}

function SelectorEjecutivo({ cobranzaId, actual }: { cobranzaId: string; actual: string | null }) {
  const qc = useQueryClient()
  const { data: ejecutivos } = useQuery({
    queryKey: ['cartera-ejecutivos'],
    queryFn: async () => (await api.get<{ id: string; nombre: string; abiertas: number }[]>('/cartera/ejecutivos')).data,
  })
  const cambiar = useMutation({
    mutationFn: (id: string) => api.put(`/cobranzas/${cobranzaId}`, { ejecutivo_id: id || null }),
    onSuccess: () => refrescarCaso(qc, cobranzaId),
    onError: (e) => alert(mensajeDeError(e)),
  })
  return (
    <select value={actual ?? ''} disabled={cambiar.isPending} aria-label="Ejecutivo asignado"
      onChange={(e) => cambiar.mutate(e.target.value)}>
      <option value="">Sin asignar</option>
      {ejecutivos?.map((u) => <option key={u.id} value={u.id}>{u.nombre}</option>)}
    </select>
  )
}

import { Fragment, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api, descargarArchivo } from '../api/client'
import type { CobranzaDetalle as Ficha, Gestion, TipoGestion } from '../api/tipos'
import { EtiquetaEstado, Plata, fechaLegible, fechaHoraLegible } from '../componentes/utiles'
import Finanzas from '../componentes/Finanzas'
import { useCampos, VistaCamposExtra } from '../componentes/CamposExtra'
import { useAuth } from '../auth'
import MensajePago from '../componentes/MensajePago'
import EnlaceDeudor from '../componentes/EnlaceDeudor'
import RegistrarGestion from '../componentes/RegistrarGestion'
import type { ResultadoGestion } from '../componentes/RegistrarGestion'
import { NuevoRecordatorio } from './Agenda'
import { fechaLocal } from '../componentes/utiles'
import { NOMBRE_DOCUMENTO } from '../componentes/utiles'

// La pantalla más usada del sistema: la ficha de una cobranza con su
// historial de gestiones y el formulario para registrar la siguiente.

export default function CobranzaDetalle() {
  const { id } = useParams()
  const { etiqueta, tiene } = useAuth()
  const [mensaje, setMensaje] = useState(false)
  const [enlace, setEnlace] = useState(false)

  const { data: cob, isLoading } = useQuery({
    queryKey: ['cobranza', id],
    queryFn: async () => (await api.get<Ficha>(`/cobranzas/${id}`)).data,
  })

  const { data: gestiones } = useQuery({
    queryKey: ['gestiones', id],
    queryFn: async () =>
      (await api.get<Gestion[]>('/gestiones/', { params: { cobranza_id: id } })).data,
  })

  const { data: tipos } = useQuery({
    queryKey: ['tipos-gestion'],
    queryFn: async () => (await api.get<TipoGestion[]>('/gestiones/tipos')).data,
  })

  // Resultado elegido en "Registrar gestión" (Finanzas puede abrirlo en modo acuerdo).
  const [resultado, setResultado] = useState<ResultadoGestion>('gestion')
  function pedirAcuerdo() {
    setResultado('acuerdo')
    document.getElementById('registrar-gestion')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const { data: campos } = useCampos('cobranza', cob?.cliente_id)

  if (isLoading || !cob) return <div className="pantalla-carga">Cargando ficha…</div>

  const nombreTipo = (tipo_id: number | null) =>
    tipos?.find((t) => t.id === tipo_id)?.nombre ?? 'Gestión'

  // Gestiones que deben saltar a la vista al recorrer el historial.
  const esDestacada = (tipo_id: number | null) =>
    ['acuerdo', 'pagado', 'abono'].includes(tipos?.find((t) => t.id === tipo_id)?.codigo ?? '')

  return (
    <>
      <header className="pagina-cabecera">
        <div>
          <Link to="/cobranzas" className="volver">← Cobranzas</Link>
          <h1>
            Cobranza N° {cob.numero}{' '}
            <EtiquetaEstado estado={cob.estado} />
          </h1>
        </div>
      </header>

      <div className="ficha-grilla">
        {/* Columna izquierda: datos del caso */}
        <section className="tarjeta">
          <h2>Datos del caso</h2>
          <dl className="datos">
            <dt>N° cobranza</dt>
            <dd className="mono negrita">{cob.numero}</dd>
            <dt>Deudor</dt>
            <dd>
              <strong>{cob.deudor?.nombre ?? '—'}</strong>
              <span className="mono suave"> {cob.deudor?.rut}</span>
              {cob.deudor?.en_boletin_comercial && <span className="etiqueta etiqueta-castigo">DICOM</span>}
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
            <dd>{cob.tipo}</dd>
            <VistaCamposExtra campos={campos} valores={cob.datos_extra} />
          </dl>
          {cob.observaciones && (
            <p className="observaciones">{cob.observaciones}</p>
          )}

          <h2 className="separado">Acciones</h2>
          <div className="acciones">
            {tiene('mensaje_pago') && (
              <button className="btn btn-primario" onClick={() => setMensaje(true)}>
                Mensaje de pago
              </button>
            )}
            {tiene('portal_deudor') && cob.deudor && (
              <button className="btn btn-secundario" onClick={() => setEnlace(true)}>
                Enlace para el deudor
              </button>
            )}
            {tiene('calculadora_369') && (
              <Link className="btn btn-secundario" to={`/calculadora?cobranza=${cob.id}`}>
                Calculadora / acuerdo 3-6-9
              </Link>
            )}
            <button
              className="btn btn-secundario"
              onClick={() => descargarArchivo(`/documentos/informe-gestiones/${cob.id}`)}
            >
              Informe de gestiones (Word)
            </button>
            <button
              className="btn btn-secundario"
              onClick={() => descargarArchivo(`/documentos/estado-cuenta/${cob.id}`)}
            >
              Estado de cuenta (Word)
            </button>
          </div>
          <div className="separado">
            <NuevoRecordatorio cobranzaId={cob.id} fecha={fechaLocal()} />
          </div>
        </section>

        {/* Columna derecha: gestiones */}
        <section className="tarjeta">
          <RegistrarGestion cobranza={cob} resultado={resultado} setResultado={setResultado} />

          <h2>Historial ({gestiones?.length ?? 0})</h2>
          <ul className="linea-tiempo">
            {gestiones?.map((g) => (
              <li key={g.id} className={esDestacada(g.tipo_id) ? 'gestion-destacada' : ''}>
                <div className="gestion-cabecera">
                  <span className="gestion-tipo">{nombreTipo(g.tipo_id)}</span>
                  <span className="suave">
                    {g.usuario_nombre && (
                      <span className="gestion-usuario">
                        {g.usuario_nombre}
                        {g.es_masivo && <span className="tag-masivo">masivo</span>}
                      </span>
                    )}
                    {fechaHoraLegible(g.fecha_gestion)}
                  </span>
                </div>
                <p>{g.descripcion}</p>
                {g.fecha_proximo_contacto && (
                  <div className="proximo-aviso">
                    Próximo contacto: {fechaLegible(g.fecha_proximo_contacto)}
                  </div>
                )}
              </li>
            ))}
            {gestiones?.length === 0 && (
              <li className="vacio">Aún no hay gestiones registradas.</li>
            )}
          </ul>
        </section>
      </div>

      <Finanzas cobranza={cob} alPedirAcuerdo={pedirAcuerdo} />
      {mensaje && <MensajePago cobranzaId={cob.id} alCerrar={() => setMensaje(false)} />}
      {enlace && cob.deudor && (
        <EnlaceDeudor deudorId={cob.deudor.id} deudorNombre={cob.deudor.nombre} cobranzaId={cob.id}
          alCerrar={() => setEnlace(false)} />
      )}
    </>
  )
}

import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { ItemAgenda, TipoItemAgenda } from '../api/tipos'
import { useAuth } from '../auth'
import { useAvisos } from '../componentes/Avisos'
import { Plata } from '../componentes/utiles'
import { ESTILO_TIPO } from './Agenda'

// Inicio: qué hay que hacer hoy. Lo atrasado y lo de hoy de la agenda,
// accesos rápidos según el área de la persona (extrajudicial, judicial o
// todo) y sus números del mes. Los totales de toda la cartera solo los ve
// quien tiene el permiso; el resto ve los suyos. El área sale del rol y cada
// uno la puede cambiar (queda guardada en este navegador).

type Area = 'extrajudicial' | 'judicial' | 'todo'

const AREA_POR_ROL: Record<string, Area> = { operador: 'extrajudicial', abogado: 'judicial', procurador: 'judicial' }
const TIPOS_DEL_AREA: Record<Area, TipoItemAgenda[]> = {
  extrajudicial: ['promesa', 'cuota', 'contacto', 'recordatorio'],
  judicial: ['plazo', 'recordatorio'],
  todo: ['plazo', 'promesa', 'cuota', 'contacto', 'recordatorio'],
}
const CLAVE_AREA = 'cartera.area'

interface Acceso { a: string; titulo: string; detalle: string; ver?: boolean }

interface MisNumeros {
  recupero: { total: string; pagos: number }
  recupero_anterior: { total: string }
  cuotas_atrasadas: number
  monto_atrasado: string
  gestiones_periodo: number
  sin_gestion_30_dias: number
}

function areaGuardada(rol: string): Area {
  try {
    const v = localStorage.getItem(CLAVE_AREA)
    if (v === 'extrajudicial' || v === 'judicial' || v === 'todo') return v
  } catch { /* sin almacenamiento */ }
  return AREA_POR_ROL[rol] ?? 'todo'
}

export default function Inicio() {
  const { usuario, tiene, puede, esAdmin } = useAuth()
  const conJudicial = tiene('judicial')
  const [area, setArea] = useState<Area>(() => (conJudicial ? areaGuardada(usuario?.rol ?? '') : 'extrajudicial'))
  const { data: avisos } = useAvisos(true)
  const totales = puede('ver_totales')
  const { data: numeros } = useQuery({
    queryKey: ['panel', 'inicio'],
    queryFn: async () => (await api.get<MisNumeros>('/panel')).data,
    staleTime: 5 * 60 * 1000,
  })

  function elegirArea(a: Area) {
    setArea(a)
    try { localStorage.setItem(CLAVE_AREA, a) } catch { /* sin almacenamiento */ }
  }

  const tipos = new Set(TIPOS_DEL_AREA[area])
  const pendientes = [...(avisos?.atrasados ?? []), ...(avisos?.hoy ?? [])].filter((i) => tipos.has(i.tipo))
  const atrasados = pendientes.filter((i) => i.atrasado).length
  const manana = (avisos?.manana ?? []).filter((i) => tipos.has(i.tipo)).length

  const accesos: Record<Area, Acceso[]> = {
    extrajudicial: [
      { a: '/abonos', titulo: 'Registrar abono', detalle: 'Busca la cobranza y anota el pago' },
      { a: '/deudores', titulo: 'Buscar deudor', detalle: 'Ficha, cobranzas y gestiones' },
      { a: '/agenda', titulo: 'Mi agenda', detalle: 'Compromisos y llamadas' },
      { a: '/calculadora', titulo: 'Calculadora 3-6-9', detalle: 'Acuerdos y honorarios', ver: tiene('calculadora_369') },
      { a: '/cobranzas/nueva', titulo: 'Ingresar cobranza', detalle: 'Una por una', ver: puede('cobranzas_crear') },
      { a: '/carga-masiva', titulo: 'Carga masiva', detalle: 'Cobranzas o gestiones desde Excel',
        ver: puede('carga_masiva') || puede('gestiones_masivas') },
    ],
    judicial: [
      { a: '/judicial', titulo: 'Causas y plazos', detalle: 'Lo que vence y lo que falta' },
      { a: '/judicial?ver=demandar', titulo: 'Para demandar', detalle: 'Cobranzas listas para la demanda' },
      { a: '/agenda', titulo: 'Mi agenda', detalle: 'Plazos y recordatorios' },
      { a: '/deudores', titulo: 'Buscar deudor', detalle: 'Ficha, cobranzas y gestiones' },
      { a: '/abonos', titulo: 'Registrar abono', detalle: 'Pagos de causas y avenimientos' },
      { a: '/gastos', titulo: 'Gastos por cliente', detalle: 'Rendiciones y reembolsos', ver: totales },
    ],
    todo: [
      { a: '/abonos', titulo: 'Registrar abono', detalle: 'Busca la cobranza y anota el pago' },
      { a: '/cobranzas/nueva', titulo: 'Ingresar cobranza', detalle: 'Una por una', ver: puede('cobranzas_crear') },
      { a: '/judicial', titulo: 'Causas y plazos', detalle: 'Lo que vence y lo que falta', ver: conJudicial },
      { a: '/panel', titulo: 'Panel', detalle: 'Recupero y cartera', ver: totales },
      { a: '/informes', titulo: 'Informes', detalle: 'Excel de gestiones y recupero', ver: totales },
      { a: '/usuarios', titulo: 'Equipo y permisos', detalle: 'Usuarios y roles', ver: esAdmin },
      { a: '/deudores', titulo: 'Buscar deudor', detalle: 'Ficha, cobranzas y gestiones' },
    ],
  }
  const visibles = accesos[area].filter((x) => x.ver !== false).slice(0, 6)

  const recupero = Number(numeros?.recupero.total ?? 0)
  const anterior = Number(numeros?.recupero_anterior.total ?? 0)
  const variacion = anterior > 0 ? Math.round(((recupero - anterior) / anterior) * 100) : null

  return (
    <>
      <header className="pagina-cabecera inicio-cabecera">
        <div>
          <h1>Hola, {usuario?.nombre.split(' ')[0]}</h1>
          <p className="suave">
            {pendientes.length === 0 ? 'No tienes nada pendiente para hoy.'
              : `${pendientes.length} ${pendientes.length === 1 ? 'pendiente' : 'pendientes'} para hoy`
                + (atrasados ? `, ${atrasados} ${atrasados === 1 ? 'atrasado' : 'atrasados'}` : '') + '.'}
            {manana > 0 && ` Mañana: ${manana}.`}
          </p>
        </div>
        {conJudicial && (
          <div className="segmentos" role="group" aria-label="Área de trabajo">
            {([['extrajudicial', 'Extrajudicial'], ['judicial', 'Judicial'], ['todo', 'Todo']] as const).map(([a, n]) => (
              <button key={a} type="button" className={area === a ? 'activo' : ''} onClick={() => elegirArea(a)}>{n}</button>
            ))}
          </div>
        )}
      </header>

      <div className="inicio-accesos">
        {visibles.map((x) => (
          <Link key={x.a} to={x.a} className="inicio-acceso">
            <strong>{x.titulo}</strong>
            <span>{x.detalle}</span>
          </Link>
        ))}
      </div>

      <div className="inicio-grilla">
        <section className="tarjeta">
          <div className="tarjeta-cabecera">
            <h2>Hoy</h2>
            <Link to="/agenda" className="btn btn-chico btn-secundario">Ver agenda completa</Link>
          </div>
          {pendientes.length === 0 ? (
            <p className="suave">Todo al día. Lo que vaya venciendo aparecerá aquí.</p>
          ) : (
            <ul className="inicio-hoy">
              {pendientes.slice(0, 12).map((i, n) => <ItemHoy key={`${i.tipo}-${i.cobranza_id ?? i.recordatorio_id}-${n}`} item={i} />)}
            </ul>
          )}
          {pendientes.length > 12 && <p className="nota">Y {pendientes.length - 12} más en la agenda.</p>}
        </section>

        <section className="tarjeta">
          <div className="tarjeta-cabecera">
            <h2>{totales ? 'El mes en la cartera' : 'Tus números del mes'}</h2>
            <Link to="/panel" className="btn btn-chico btn-secundario">Panel</Link>
          </div>
          {numeros ? (
            <div className="inicio-cifras">
              <div className="inicio-cifra">
                <span>Recuperado</span>
                <strong><Plata valor={recupero} /></strong>
                {variacion != null && (
                  <span className={variacion >= 0 ? 'texto-verde' : 'texto-rojo'}>
                    {variacion >= 0 ? '+' : ''}{variacion} % vs. el mes anterior
                  </span>
                )}
              </div>
              <div className="inicio-cifra">
                <span>Cuotas atrasadas</span>
                <strong>{numeros.cuotas_atrasadas}</strong>
                {numeros.cuotas_atrasadas > 0 && <span className="suave"><Plata valor={numeros.monto_atrasado} /></span>}
              </div>
              <div className="inicio-cifra">
                <span>Gestiones</span>
                <strong>{numeros.gestiones_periodo}</strong>
                <span className="suave">{numeros.recupero.pagos} pagos</span>
              </div>
              <div className="inicio-cifra">
                <span>Sin gestión hace 30 días</span>
                <strong className={numeros.sin_gestion_30_dias > 0 ? 'texto-rojo-fuerte' : ''}>{numeros.sin_gestion_30_dias}</strong>
              </div>
            </div>
          ) : <p className="suave">Cargando…</p>}
        </section>
      </div>
    </>
  )
}

function ItemHoy({ item }: { item: ItemAgenda }) {
  const estilo = ESTILO_TIPO[item.tipo]
  const destino = item.causa_id ? `/judicial/causas/${item.causa_id}` : item.cobranza_id ? `/cobranzas/${item.cobranza_id}` : '/agenda'
  return (
    <li>
      <Link to={destino} className="inicio-item">
        <span className="inicio-punto" style={{ background: estilo.color }} aria-hidden="true" />
        <span className="inicio-item-texto">
          <strong>{item.titulo}</strong>
          <span className="suave">{estilo.nombre}{item.hora ? ` · ${item.hora.slice(0, 5)}` : ''}</span>
        </span>
        {item.atrasado && <span className="etiqueta etiqueta-castigo">Atrasado</span>}
        {item.monto ? <span className="inicio-monto"><Plata valor={item.monto} /></span> : null}
      </Link>
    </li>
  )
}

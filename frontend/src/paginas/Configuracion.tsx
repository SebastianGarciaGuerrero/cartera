import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, mensajeDeError } from '../api/client'
import { useAuth } from '../auth'
import type { CampoPersonalizado, Cliente, TipoCampo, TipoGestion } from '../api/tipos'

// Configuración (solo admin): lo que cada estudio adapta por su cuenta,
// sin pedir cambios de código.
//  - Etiquetas: cómo se llaman las cosas en la interfaz (Mandante, Sucursal...).
//  - Campos personalizados: datos propios en cobranzas y deudores.
//  - Tipos de gestión propios.

type Pestana = 'campos' | 'etiquetas' | 'tipos' | 'cobro'

export default function Configuracion() {
  const [pestana, setPestana] = useState<Pestana>('campos')
  return (
    <>
      <header className="pagina-cabecera">
        <h1>Configuración</h1>
      </header>
      <div className="pestanas">
        {([['campos', 'Campos personalizados'], ['etiquetas', 'Nombres en pantalla'],
           ['tipos', 'Tipos de gestión'], ['cobro', 'Cobro']] as const).map(([clave, nombre]) => (
          <button key={clave} className={`pestana ${pestana === clave ? 'activa' : ''}`}
            onClick={() => setPestana(clave)}>{nombre}</button>
        ))}
      </div>
      {pestana === 'campos' && <Campos />}
      {pestana === 'etiquetas' && <Etiquetas />}
      {pestana === 'tipos' && <TiposGestion />}
      {pestana === 'cobro' && <Cobro />}
    </>
  )
}

// ------------------------------------------------------------ campos

const NOMBRE_TIPO: Record<TipoCampo, string> = {
  texto: 'Texto', numero: 'Número', monto: 'Monto ($)', fecha: 'Fecha',
  seleccion: 'Lista de opciones', si_no: 'Sí / No',
}

function Campos() {
  const qc = useQueryClient()
  const { data: campos } = useQuery({
    queryKey: ['campos', 'todos'],
    queryFn: async () =>
      (await api.get<CampoPersonalizado[]>('/campos', { params: { incluir_inactivos: true } })).data,
  })
  const { data: clientes } = useQuery({
    queryKey: ['clientes'],
    queryFn: async () => (await api.get<Cliente[]>('/clientes/')).data,
  })
  const nombreCliente = (id: string | null) =>
    id ? (clientes?.find((c) => c.id === id)?.nombre_fantasia ?? clientes?.find((c) => c.id === id)?.razon_social ?? '—') : 'Todos'

  const [entidad, setEntidad] = useState<'cobranza' | 'deudor'>('cobranza')
  const [etiqueta, setEtiqueta] = useState('')
  const [tipo, setTipo] = useState<TipoCampo>('texto')
  const [opciones, setOpciones] = useState('')
  const [clienteId, setClienteId] = useState('')
  const [obligatorio, setObligatorio] = useState(false)
  const [error, setError] = useState('')

  const crear = useMutation({
    mutationFn: () => api.post('/campos', {
      entidad, etiqueta, tipo, obligatorio,
      opciones: tipo === 'seleccion' ? opciones.split(',').map((o) => o.trim()).filter(Boolean) : [],
      cliente_id: clienteId || null,
      orden: (campos?.length ?? 0) * 10,
    }),
    onSuccess: () => {
      setEtiqueta(''); setOpciones(''); setObligatorio(false); setError('')
      qc.invalidateQueries({ queryKey: ['campos'] })
    },
    onError: (err) => setError(mensajeDeError(err)),
  })
  const alternar = useMutation({
    mutationFn: (c: CampoPersonalizado) => api.put(`/campos/${c.id}`, { activo: !c.activo }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['campos'] }),
  })

  function alEnviar(e: FormEvent) {
    e.preventDefault()
    crear.mutate()
  }

  return (
    <>
      <p className="nota">
        Agrega los datos propios de tu cartera: "Previsión" para una clínica, "Patente" para una
        automotora, "N° de contrato" para una inmobiliaria. Aparecen en el alta de cobranzas, en
        la ficha y como columnas en la plantilla de carga masiva. Si lo limitas a un cliente, solo
        aparece en sus cobranzas.
      </p>
      <table className="tabla">
        <thead>
          <tr><th>Campo</th><th>En</th><th>Tipo</th><th>Cliente</th><th>Obligatorio</th><th>Estado</th><th></th></tr>
        </thead>
        <tbody>
          {campos?.map((c) => (
            <tr key={c.id} className={c.activo ? '' : 'suave'}>
              <td>{c.etiqueta} <span className="mono suave">{c.clave}</span></td>
              <td>{c.entidad === 'cobranza' ? 'Cobranza' : 'Deudor'}</td>
              <td>{NOMBRE_TIPO[c.tipo]}{c.tipo === 'seleccion' && <span className="suave"> ({c.opciones.join(', ')})</span>}</td>
              <td>{nombreCliente(c.cliente_id)}</td>
              <td>{c.obligatorio ? 'Sí' : 'No'}</td>
              <td>{c.activo ? 'Activo' : 'Desactivado'}</td>
              <td>
                <button className="btn btn-chico btn-secundario" onClick={() => alternar.mutate(c)}>
                  {c.activo ? 'Desactivar' : 'Activar'}
                </button>
              </td>
            </tr>
          ))}
          {campos?.length === 0 && (
            <tr><td colSpan={7} className="vacio">Todavía no hay campos personalizados.</td></tr>
          )}
        </tbody>
      </table>

      <form className="form-finanzas form-alta" onSubmit={alEnviar}>
        <h3>Nuevo campo</h3>
        <div className="fila">
          <label>Nombre del campo *
            <input value={etiqueta} onChange={(e) => setEtiqueta(e.target.value)} maxLength={100} required
              placeholder="Ej. Previsión" />
          </label>
          <label>Se usa en
            <select value={entidad} onChange={(e) => setEntidad(e.target.value as 'cobranza' | 'deudor')}>
              <option value="cobranza">Cobranzas</option>
              <option value="deudor">Deudores</option>
            </select>
          </label>
          <label>Tipo de dato
            <select value={tipo} onChange={(e) => setTipo(e.target.value as TipoCampo)}>
              {Object.entries(NOMBRE_TIPO).map(([v, n]) => <option key={v} value={v}>{n}</option>)}
            </select>
          </label>
        </div>
        <div className="fila">
          {tipo === 'seleccion' && (
            <label>Opciones (separadas por coma) *
              <input value={opciones} onChange={(e) => setOpciones(e.target.value)} placeholder="FONASA, ISAPRE" />
            </label>
          )}
          {entidad === 'cobranza' && (
            <label>Solo para el cliente
              <select value={clienteId} onChange={(e) => setClienteId(e.target.value)}>
                <option value="">Todos los clientes</option>
                {clientes?.map((c) => <option key={c.id} value={c.id}>{c.nombre_fantasia ?? c.razon_social}</option>)}
              </select>
            </label>
          )}
          <label className="check">
            <input type="checkbox" checked={obligatorio} onChange={(e) => setObligatorio(e.target.checked)} />
            Obligatorio
          </label>
        </div>
        {error && <div className="alerta-error">{error}</div>}
        <div className="fila">
          <button className="btn btn-primario" disabled={crear.isPending}>Agregar campo</button>
        </div>
      </form>
    </>
  )
}

// ------------------------------------------------------------ etiquetas

interface VistaOrganizacion { nombre: string; etiquetas: Record<string, string> }

const ETIQUETAS: [string, string][] = [
  ['cliente', 'Cliente (singular)'], ['clientes', 'Clientes (plural)'],
  ['filial', 'Filial (singular)'], ['filiales', 'Filiales (plural)'],
  ['deudor', 'Deudor (singular)'], ['deudores', 'Deudores (plural)'],
  ['id_externo', 'ID del cliente'], ['numero_operacion', 'N° de operación'],
  ['ejecutivo', 'Ejecutivo'], ['fecha_origen', 'Fecha de origen de la deuda'],
]

function Etiquetas() {
  const { recargar } = useAuth()
  const { data } = useQuery({
    queryKey: ['organizacion'],
    queryFn: async () => (await api.get<VistaOrganizacion>('/organizacion')).data,
  })
  const [form, setForm] = useState<Record<string, string>>({})
  const [nombre, setNombre] = useState('')
  const [ok, setOk] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    if (data) { setForm(data.etiquetas); setNombre(data.nombre) }
  }, [data])

  const guardar = useMutation({
    mutationFn: () => api.put('/organizacion', { nombre, etiquetas: form }),
    onSuccess: async () => { setOk(true); setError(''); await recargar() },
    onError: (err) => { setOk(false); setError(mensajeDeError(err)) },
  })

  return (
    <form className="form-finanzas form-alta" onSubmit={(e) => { e.preventDefault(); guardar.mutate() }}>
      <p className="nota">
        Usa el vocabulario de tu estudio: por ejemplo "Mandante" en vez de "Cliente", o "Sucursal"
        en vez de "Filial". Los cambios se ven en menús, formularios y fichas.
      </p>
      <label>Nombre de la organización
        <input value={nombre} onChange={(e) => setNombre(e.target.value)} maxLength={200} />
      </label>
      <div className="fila" style={{ flexWrap: 'wrap' }}>
        {ETIQUETAS.map(([clave, descripcion]) => (
          <label key={clave}>{descripcion}
            <input value={form[clave] ?? ''} maxLength={40}
              onChange={(e) => { setOk(false); setForm((f) => ({ ...f, [clave]: e.target.value })) }} />
          </label>
        ))}
      </div>
      {error && <div className="alerta-error">{error}</div>}
      {ok && <div className="alerta-exito">Guardado.</div>}
      <div className="fila">
        <button className="btn btn-primario" disabled={guardar.isPending}>Guardar</button>
      </div>
    </form>
  )
}

// ------------------------------------------------------------ tipos de gestión

const CATEGORIAS = [
  ['contacto', 'Contacto'], ['pago', 'Pago / compromiso'], ['negativo', 'Negativo'],
  ['judicial', 'Judicial'], ['otro', 'Otro'],
] as const

function TiposGestion() {
  const qc = useQueryClient()
  const { data: tipos } = useQuery({
    queryKey: ['tipos-gestion', 'todos'],
    queryFn: async () => (await api.get<TipoGestion[]>('/gestiones/tipos', { params: { solo_activos: false } })).data,
  })
  const [nombre, setNombre] = useState('')
  const [categoria, setCategoria] = useState('contacto')
  const [error, setError] = useState('')
  const crear = useMutation({
    mutationFn: () => api.post('/gestiones/tipos', { nombre, categoria }),
    onSuccess: () => { setNombre(''); setError(''); qc.invalidateQueries({ queryKey: ['tipos-gestion'] }) },
    onError: (err) => setError(mensajeDeError(err)),
  })
  const alternar = useMutation({
    mutationFn: (t: TipoGestion) => api.put(`/gestiones/tipos/${t.id}`, { nombre: t.nombre, categoria: t.categoria, activo: !t.activo }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['tipos-gestion'] }),
  })

  return (
    <>
      <table className="tabla">
        <thead><tr><th>Tipo</th><th>Categoría</th><th>Origen</th><th></th></tr></thead>
        <tbody>
          {tipos?.map((t) => (
            <tr key={t.id} className={t.activo ? '' : 'suave'}>
              <td>{t.nombre}</td>
              <td>{CATEGORIAS.find(([v]) => v === t.categoria)?.[1]}</td>
              <td>{t.propio ? 'Propio' : 'Del sistema'}</td>
              <td>
                {t.propio && (
                  <button className="btn btn-chico btn-secundario" onClick={() => alternar.mutate(t)}>
                    {t.activo ? 'Desactivar' : 'Activar'}
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <form className="form-finanzas form-alta" onSubmit={(e) => { e.preventDefault(); crear.mutate() }}>
        <h3>Nuevo tipo de gestión</h3>
        <div className="fila">
          <label>Nombre *
            <input value={nombre} onChange={(e) => setNombre(e.target.value)} required minLength={2} maxLength={100}
              placeholder="Ej. Visita notario" />
          </label>
          <label>Categoría
            <select value={categoria} onChange={(e) => setCategoria(e.target.value)}>
              {CATEGORIAS.map(([v, n]) => <option key={v} value={v}>{n}</option>)}
            </select>
          </label>
        </div>
        {error && <div className="alerta-error">{error}</div>}
        <div className="fila"><button className="btn btn-primario" disabled={crear.isPending}>Agregar</button></div>
      </form>
    </>
  )
}

// ------------------------------------------------------------ cobro

interface VistaCobro {
  plantilla_mensaje_pago: string
  cobro: { pct_judicial: string; comision_pct: string }
}

const MARCADORES = ['{deudor}', '{nombre}', '{saldo}', '{numero}', '{id_externo}', '{cliente}',
  '{empresa}', '{datos_pago}', '{telefono_empresa}', '{email_empresa}']

function Cobro() {
  const { data } = useQuery({
    queryKey: ['organizacion'],
    queryFn: async () => (await api.get<VistaCobro>('/organizacion')).data,
  })
  const qc = useQueryClient()
  const [plantilla, setPlantilla] = useState('')
  const [pctJudicial, setPctJudicial] = useState('10')
  const [comision, setComision] = useState('2.2491')
  const [ok, setOk] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    if (data) {
      setPlantilla(data.plantilla_mensaje_pago)
      setPctJudicial(String(Number(data.cobro.pct_judicial)))
      setComision(String(Number(data.cobro.comision_pct)))
    }
  }, [data])

  const guardar = useMutation({
    mutationFn: () => api.put('/organizacion', {
      plantilla_mensaje_pago: plantilla,
      cobro: { pct_judicial: pctJudicial, comision_pct: comision },
    }),
    onSuccess: () => { setOk(true); setError(''); qc.invalidateQueries({ queryKey: ['organizacion'] }) },
    onError: (err) => { setOk(false); setError(mensajeDeError(err)) },
  })

  return (
    <form className="form-finanzas form-alta" onSubmit={(e) => { e.preventDefault(); guardar.mutate() }}>
      <h3>Mensaje de pago</h3>
      <p className="nota">
        Texto que se arma en cada cobranza con el botón "Mensaje de pago". Puedes usar estos
        marcadores: {MARCADORES.map((m) => <span key={m} className="mono">{m} </span>)}.
        Los datos de transferencia salen de Mi empresa (o del cliente, si tiene propios).
      </p>
      <textarea rows={12} value={plantilla} onChange={(e) => { setOk(false); setPlantilla(e.target.value) }} />
      <h3>Calculadora</h3>
      <div className="fila">
        <label>Honorarios judiciales (%)
          <input type="number" min="0" max="30" step="0.01" value={pctJudicial}
            onChange={(e) => { setOk(false); setPctJudicial(e.target.value) }} />
        </label>
        <label>Comisión de pago en línea (%)
          <input type="number" min="0" max="10" step="0.0001" value={comision}
            onChange={(e) => { setOk(false); setComision(e.target.value) }} />
        </label>
      </div>
      <p className="nota">Los tramos extrajudiciales 3-6-9 son los del art. 37 de la Ley 19.496 y no se cambian.</p>
      {error && <div className="alerta-error">{error}</div>}
      {ok && <div className="alerta-exito">Guardado.</div>}
      <div className="fila"><button className="btn btn-primario" disabled={guardar.isPending}>Guardar</button></div>
    </form>
  )
}

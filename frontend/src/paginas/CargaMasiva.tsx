import { useState } from 'react'
import type { ChangeEvent } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { api, descargarArchivo, mensajeDeError } from '../api/client'
import type { Cliente } from '../api/tipos'

// Carga masiva desde Excel, en dos modos:
//  - Cobranzas nuevas: una fila por cobranza (crea deudor + cobranza).
//  - Gestiones: registra gestiones en bloque sobre cobranzas existentes de
//    un cliente, identificadas por su ID cliente. Quedan marcadas "masivo".

export default function CargaMasiva() {
  const [pestana, setPestana] = useState<'cobranzas' | 'gestiones'>('cobranzas')

  return (
    <>
      <header className="pagina-cabecera">
        <h1>Cargas masivas</h1>
      </header>

      <div className="pestanas">
        <button
          className={pestana === 'cobranzas' ? 'pestana activa' : 'pestana'}
          onClick={() => setPestana('cobranzas')}
        >
          Cobranzas nuevas
        </button>
        <button
          className={pestana === 'gestiones' ? 'pestana activa' : 'pestana'}
          onClick={() => setPestana('gestiones')}
        >
          Gestiones
        </button>
      </div>

      {pestana === 'cobranzas' ? <CargaCobranzas /> : <CargaGestiones />}
    </>
  )
}

// ------------------------------------------------------------
// Cobranzas nuevas
// ------------------------------------------------------------

interface ResultadoCobranzas {
  filas_procesadas: number
  cobranzas_creadas: number
  deudores_nuevos: number
  errores: { fila: number; error: string }[]
}

const CAMPOS_COBRANZA: [string, boolean, string][] = [
  ['RUT deudor', true, 'Formato 12345678-9. Si el deudor ya existe, se reutiliza (no se duplica).'],
  ['Nombre deudor', true, 'Nombre completo. Solo se usa si el deudor es nuevo.'],
  ['Teléfono', false, 'Se guarda como contacto del deudor (si es nuevo).'],
  ['Email', false, 'Se guarda como contacto del deudor (si es nuevo).'],
  ['Cliente', true, 'Debe existir en el sistema. Se busca por nombre.'],
  ['Filial', false, 'Sucursal del cliente (ej: Valparaíso). Debe existir si se indica.'],
  ['ID cliente', false, 'N° interno del cliente (SAP, HIS…). No puede repetirse para el mismo cliente.'],
  ['Monto deuda', true, 'Capital adeudado, solo números (ej: 450000).'],
  ['Tipo documento', false, 'pagare, factura, letra, cheque u otro. Si se omite: pagare.'],
  ['N° documento', false, 'N° del pagaré, factura, etc.'],
  ['Fecha atención', false, 'Formato AAAA-MM-DD (ej: 2026-05-12).'],
  ['Previsión', false, 'FONASA, ISAPRE…'],
  ['Observaciones', false, 'Texto libre.'],
]

function CargaCobranzas() {
  const [resultado, setResultado] = useState<ResultadoCobranzas | null>(null)
  const [error, setError] = useState('')

  const subir = useMutation({
    mutationFn: async (archivo: File) => {
      const form = new FormData()
      form.append('archivo', archivo)
      const { data } = await api.post<ResultadoCobranzas>('/importar/cobranzas', form)
      return data
    },
    onSuccess: (data) => { setResultado(data); setError('') },
    onError: (err) => { setResultado(null); setError(mensajeDeError(err)) },
  })

  function alElegirArchivo(e: ChangeEvent<HTMLInputElement>) {
    const archivo = e.target.files?.[0]
    if (archivo) subir.mutate(archivo)
    e.target.value = ''
  }

  return (
    <div className="ficha-grilla">
      <section className="tarjeta">
        <h2>Paso 1 · Descargar formato</h2>
        <p className="suave">
          Descarga el Excel de formato, llénalo con una fila por cobranza y
          guárdalo. La primera fila trae un ejemplo que puedes borrar.
        </p>
        <button className="btn btn-secundario" onClick={() => descargarArchivo('/importar/plantilla')}>
          Descargar Excel de formato
        </button>

        <h2 className="paso-titulo">Paso 2 · Subir el archivo lleno</h2>
        <p className="suave">
          Las filas correctas se ingresan aunque otras tengan errores; abajo
          verás el detalle de las que fallaron para corregirlas y resubirlas.
        </p>
        <label className="btn btn-primario subir-archivo">
          {subir.isPending ? 'Procesando…' : 'Subir formato lleno'}
          <input type="file" accept=".xlsx" onChange={alElegirArchivo} disabled={subir.isPending} hidden />
        </label>

        {error && <div className="alerta-error">{error}</div>}
        {resultado && (
          <div className="resultado-carga">
            <p>
              <strong>{resultado.cobranzas_creadas}</strong> cobranzas creadas
              de {resultado.filas_procesadas} filas
              ({resultado.deudores_nuevos} deudores nuevos).
            </p>
            <ListaErrores errores={resultado.errores} />
          </div>
        )}
      </section>

      <TablaColumnas campos={CAMPOS_COBRANZA} />
    </div>
  )
}

// ------------------------------------------------------------
// Gestiones
// ------------------------------------------------------------

interface ResultadoGestiones {
  filas_procesadas: number
  gestiones_creadas: number
  errores: { fila: number; error: string }[]
}

const CAMPOS_GESTION: [string, boolean, string][] = [
  ['ID cliente', true, 'El ID interno con que el cliente identifica la cobranza. Se busca dentro del cliente elegido arriba.'],
  ['Fecha', false, 'Cuándo se hizo la gestión (AAAA-MM-DD). Si se omite: hoy.'],
  ['Gestión', true, 'El texto de la gestión (qué se hizo).'],
  ['Persona', true, 'Quién la realizó. Debe ser un usuario del sistema (ej: GRV). Quedará marcada como "masivo".'],
]

function CargaGestiones() {
  const [clienteId, setClienteId] = useState('')
  const [resultado, setResultado] = useState<ResultadoGestiones | null>(null)
  const [error, setError] = useState('')

  const { data: clientes } = useQuery({
    queryKey: ['clientes'],
    queryFn: async () => (await api.get<Cliente[]>('/clientes/')).data,
  })

  const subir = useMutation({
    mutationFn: async (archivo: File) => {
      const form = new FormData()
      form.append('cliente_id', clienteId)
      form.append('archivo', archivo)
      const { data } = await api.post<ResultadoGestiones>('/importar/gestiones', form)
      return data
    },
    onSuccess: (data) => { setResultado(data); setError('') },
    onError: (err) => { setResultado(null); setError(mensajeDeError(err)) },
  })

  function alElegirArchivo(e: ChangeEvent<HTMLInputElement>) {
    const archivo = e.target.files?.[0]
    if (archivo) subir.mutate(archivo)
    e.target.value = ''
  }

  return (
    <div className="ficha-grilla">
      <section className="tarjeta">
        <h2>Paso 1 · Elegir el cliente</h2>
        <p className="suave">
          Los ID pueden repetirse entre clientes distintos, así
          que primero indica a cuál pertenecen las gestiones de tu planilla.
        </p>
        <label>
          Cliente
          <select value={clienteId} onChange={(e) => setClienteId(e.target.value)}>
            <option value="">Seleccionar cliente…</option>
            {clientes?.map((c) => (
              <option key={c.id} value={c.id}>{c.nombre_fantasia ?? c.razon_social}</option>
            ))}
          </select>
        </label>

        <h2 className="paso-titulo">Paso 2 · Descargar formato</h2>
        <p className="suave">
          Una fila por gestión: ID cliente de la cobranza, fecha, el texto y la
          persona que la hizo.
        </p>
        <button className="btn btn-secundario" onClick={() => descargarArchivo('/importar/plantilla-gestiones')}>
          Descargar Excel de formato
        </button>

        <h2 className="paso-titulo">Paso 3 · Subir el archivo lleno</h2>
        <p className="suave">
          Las gestiones quedan registradas en el historial de cada cobranza,
          marcadas como <strong>masivo</strong> junto al nombre de la persona.
        </p>
        <label
          className={`btn btn-primario subir-archivo ${clienteId ? '' : 'btn-deshabilitado'}`}
          title={clienteId ? '' : 'Primero elige el cliente'}
        >
          {subir.isPending ? 'Procesando…' : 'Subir formato lleno'}
          <input type="file" accept=".xlsx" onChange={alElegirArchivo}
            disabled={subir.isPending || !clienteId} hidden />
        </label>

        {error && <div className="alerta-error">{error}</div>}
        {resultado && (
          <div className="resultado-carga">
            <p>
              <strong>{resultado.gestiones_creadas}</strong> gestiones
              registradas de {resultado.filas_procesadas} filas.
            </p>
            <ListaErrores errores={resultado.errores} />
          </div>
        )}
      </section>

      <TablaColumnas campos={CAMPOS_GESTION} />
    </div>
  )
}

// ------------------------------------------------------------
// Piezas compartidas
// ------------------------------------------------------------

function TablaColumnas({ campos }: { campos: [string, boolean, string][] }) {
  return (
    <section className="tarjeta">
      <h2>Columnas del formato</h2>
      <table className="tabla">
        <thead>
          <tr><th>Columna</th><th>¿Obligatoria?</th><th>Detalle</th></tr>
        </thead>
        <tbody>
          {campos.map(([nombre, obligatorio, detalle]) => (
            <tr key={nombre}>
              <td className="negrita">{nombre}</td>
              <td>
                {obligatorio
                  ? <span className="etiqueta etiqueta-castigo">Obligatoria</span>
                  : <span className="etiqueta etiqueta-archivada">Opcional</span>}
              </td>
              <td className="suave">{detalle}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

function ListaErrores({ errores }: { errores: { fila: number; error: string }[] }) {
  if (errores.length === 0) return null
  return (
    <>
      <p className="suave">Filas con problemas ({errores.length}):</p>
      <ul className="lista-errores">
        {errores.map((e) => (
          <li key={e.fila}>
            <span className="mono">Fila {e.fila}:</span> {e.error}
          </li>
        ))}
      </ul>
    </>
  )
}

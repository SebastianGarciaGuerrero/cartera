import { useEffect, useMemo, useState } from 'react'
import type { ChangeEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, descargarArchivo, mensajeDeError } from '../api/client'
import type { Cliente, HojaAnalizada, ResultadoCarga, Trabajo } from '../api/tipos'
import { useAuth } from '../auth'

// Carga masiva desde Excel, en dos modos:
//  - Cobranzas: reconoce las columnas por su título (también los de la
//    planilla del cliente: "Rut Deudor", "Mail Deudor", "Saldo Capital"…),
//    varias hojas, terceros (paciente, aval) y, para el administrador,
//    actualizar las cobranzas que ya existen.
//  - Gestiones: con su tipo, fecha, persona y próximo contacto; cada fila
//    se ubica por N° de cobranza, ID cliente o RUT del deudor.
// Las cargas corren en segundo plano: se ve el avance y el resultado.

export default function CargaMasiva() {
  const { puede } = useAuth()
  const [pestana, setPestana] = useState<'cobranzas' | 'gestiones'>(puede('carga_masiva') ? 'cobranzas' : 'gestiones')

  return (
    <>
      <header className="pagina-cabecera">
        <h1>Cargas masivas</h1>
      </header>

      <div className="pestanas">
        {puede('carga_masiva') && (
          <button className={pestana === 'cobranzas' ? 'pestana activa' : 'pestana'} onClick={() => setPestana('cobranzas')}>
            Cobranzas
          </button>
        )}
        {puede('gestiones_masivas') && (
          <button className={pestana === 'gestiones' ? 'pestana activa' : 'pestana'} onClick={() => setPestana('gestiones')}>
            Gestiones
          </button>
        )}
      </div>

      {pestana === 'cobranzas' ? <CargaCobranzas /> : <CargaGestiones />}
    </>
  )
}

// ------------------------------------------------------------ avance

function useTrabajo(id: string | null) {
  return useQuery({
    queryKey: ['trabajo', id],
    enabled: Boolean(id),
    queryFn: async () => (await api.get<Trabajo>(`/importar/trabajos/${id}`)).data,
    refetchInterval: (q) => (q.state.data && ['terminado', 'error'].includes(q.state.data.estado) ? false : 1500),
  })
}

function descargarErrores(r: ResultadoCarga) {
  const lineas = ['Hoja;Fila;Error', ...r.errores.map((e) => `${e.hoja};${e.fila};"${e.error.replace(/"/g, "'")}"`)]
  const url = URL.createObjectURL(new Blob(['﻿' + lineas.join('\n')], { type: 'text/csv;charset=utf-8' }))
  const a = document.createElement('a')
  a.href = url
  a.download = 'errores_carga.csv'
  a.click()
  URL.revokeObjectURL(url)
}

function Progreso({ trabajoId, alTerminar }: { trabajoId: string; alTerminar?: () => void }) {
  const qc = useQueryClient()
  const { data: t } = useTrabajo(trabajoId)
  const termino = Boolean(t) && !['en_cola', 'procesando'].includes(t!.estado)
  // Al terminar, lo cargado aparece en el resto de las pantallas.
  useEffect(() => {
    if (!termino) return
    for (const queryKey of [['cobranzas'], ['deudores'], ['gestiones'], ['agenda'], ['avisos'], ['panel'], ['clientes'], ['campos']]) {
      qc.invalidateQueries({ queryKey })
    }
    alTerminar?.()
  }, [termino, qc, alTerminar])
  if (!t) return <p className="suave">Iniciando la carga…</p>
  const enCurso = !termino
  const pct = t.total > 0 ? Math.round((t.procesadas / t.total) * 100) : 0
  const r = t.resultado
  return (
    <div className="resultado-carga">
      {enCurso && (
        <>
          <p><strong>Cargando {t.archivo}…</strong> {t.total > 0 && `${t.procesadas.toLocaleString('es-CL')} de ${t.total.toLocaleString('es-CL')} filas`}</p>
          <div className="barra-avance" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
            <span style={{ width: `${pct}%` }} />
          </div>
          <p className="nota">Puedes seguir trabajando: la carga sigue aunque cambies de pantalla.</p>
        </>
      )}
      {t.estado === 'error' && <div className="alerta-error">{r?.error ?? 'La carga falló.'}</div>}
      {t.estado === 'terminado' && r && (
        <>
          <div className="alerta-exito">Carga terminada: {r.filas_procesadas.toLocaleString('es-CL')} filas revisadas.</div>
          <ul className="lista-simple">
            {r.cobranzas_creadas > 0 && <li><span>Cobranzas creadas</span><strong>{r.cobranzas_creadas.toLocaleString('es-CL')}</strong></li>}
            {r.cobranzas_actualizadas > 0 && <li><span>Cobranzas actualizadas</span><strong>{r.cobranzas_actualizadas.toLocaleString('es-CL')}</strong></li>}
            {r.ya_existian > 0 && <li><span>Ya existían (no se tocaron)</span><strong>{r.ya_existian.toLocaleString('es-CL')}</strong></li>}
            {r.deudores_nuevos > 0 && <li><span>Deudores nuevos</span><strong>{r.deudores_nuevos.toLocaleString('es-CL')}</strong></li>}
            {r.contactos_agregados > 0 && <li><span>Teléfonos y correos agregados a deudores existentes</span><strong>{r.contactos_agregados.toLocaleString('es-CL')}</strong></li>}
            {r.gestiones_creadas > 0 && <li><span>Gestiones registradas</span><strong>{r.gestiones_creadas.toLocaleString('es-CL')}</strong></li>}
            {r.filiales_creadas.length > 0 && <li><span>Filiales creadas</span><strong>{r.filiales_creadas.join(', ')}</strong></li>}
            {r.campos_creados.length > 0 && <li><span>Datos adicionales creados</span><strong>{r.campos_creados.join(', ')}</strong></li>}
            <li><span>Filas con error</span><strong className={r.total_errores ? 'texto-rojo' : ''}>{r.total_errores.toLocaleString('es-CL')}</strong></li>
          </ul>
          {r.avisos.length > 0 && (
            <div className="observaciones"><strong>Avisos:</strong> {r.avisos.join(' · ')}</div>
          )}
          {r.errores.length > 0 && (
            <>
              <div className="acciones-fila separado">
                <button className="btn btn-chico btn-secundario" onClick={() => descargarErrores(r)}>Descargar errores (Excel/CSV)</button>
              </div>
              <div className="tabla-desplazable errores-carga">
                <table className="tabla">
                  <thead><tr><th>Hoja</th><th>Fila</th><th>Error</th></tr></thead>
                  <tbody>
                    {r.errores.slice(0, 200).map((e, i) => (
                      <tr key={i}><td>{e.hoja}</td><td className="mono">{e.fila}</td><td>{e.error}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="nota">Corrige esas filas en el Excel y vuelve a subirlo: lo que ya entró se salta solo.</p>
            </>
          )}
        </>
      )}
    </div>
  )
}

// ------------------------------------------------------------ cobranzas

const NOMBRE_CLAVE: Record<string, string> = {
  rut: 'RUT deudor', nombre: 'Nombre deudor', telefono: 'Teléfono', email: 'Correo', direccion: 'Dirección',
  comuna: 'Comuna', ciudad: 'Ciudad', region: 'Región', cliente: 'Cliente', filial: 'Filial', id_externo: 'ID cliente',
  monto: 'Monto', tipo_documento: 'Tipo documento', numero_documento: 'N° documento', n_pagare: 'N° pagaré',
  n_factura: 'N° factura', n_cheque: 'N° cheque', n_letra: 'N° letra', fecha_vencimiento_documento: 'Vencimiento',
  fecha_origen: 'Fecha origen', fecha_ingreso: 'Fecha de ingreso', fecha_traspaso: 'Fecha traspaso', dicom: 'DICOM',
  estado: 'Estado / etapa', ejecutivo: 'Ejecutivo', observaciones: 'Observaciones',
  autorizacion_firma: 'Autorización de firma', comprobante_envio: 'Comprobante de envío',
  fecha_envio_documentos: 'Envío de documentos',
  t_rut: 'RUT', t_nombre: 'Nombre', t_telefono: 'Teléfono', t_email: 'Correo', t_direccion: 'Dirección',
  t_comuna: 'Comuna', t_ciudad: 'Ciudad', t_region: 'Región',
}

function nombreColumna(clave: string, rol: string | null) {
  const base = NOMBRE_CLAVE[clave] ?? clave
  return clave.startsWith('t_') ? `${base} ${rol ?? 'tercero'}` : base
}

function CargaCobranzas() {
  const { esAdmin } = useAuth()
  const [archivo, setArchivo] = useState<File | null>(null)
  const [hojas, setHojas] = useState<HojaAnalizada[] | null>(null)
  const [elegidas, setElegidas] = useState<string[]>([])
  const [extras, setExtras] = useState<string[]>([])
  const [clienteId, setClienteId] = useState('')
  const [crearFiliales, setCrearFiliales] = useState(true)
  const [actualizar, setActualizar] = useState(false)
  const [trabajoId, setTrabajoId] = useState<string | null>(null)
  const [error, setError] = useState('')

  const { data: clientes } = useQuery({
    queryKey: ['clientes'],
    queryFn: async () => (await api.get<Cliente[]>('/clientes/')).data,
  })

  const analizar = useMutation({
    mutationFn: async (f: File) => {
      const form = new FormData()
      form.append('archivo', f)
      return (await api.post<{ hojas: HojaAnalizada[] }>('/importar/analizar', form)).data.hojas
    },
    onSuccess: (h) => {
      setHojas(h)
      // Con varias hojas (p. ej. una por filial) se eligen a mano: así no se carga de más sin querer.
      const sirven = h.filter((x) => x.sirve)
      setElegidas(sirven.length === 1 ? [sirven[0].nombre] : [])
      setExtras([])
      setError(h.some((x) => x.sirve) ? '' : 'Ninguna hoja tiene al menos las columnas RUT y nombre del deudor.')
    },
    onError: (e) => { setHojas(null); setError(mensajeDeError(e)) },
  })

  const cargar = useMutation({
    mutationFn: async () => {
      const form = new FormData()
      form.append('archivo', archivo!)
      if (clienteId) form.append('cliente_id', clienteId)
      form.append('hojas', JSON.stringify(elegidas))
      form.append('columnas_extra', JSON.stringify(extras))
      form.append('crear_filiales', String(crearFiliales))
      form.append('actualizar', String(actualizar))
      return (await api.post<{ trabajo_id: string }>('/importar/cobranzas', form)).data.trabajo_id
    },
    onSuccess: (id) => { setTrabajoId(id); setError('') },
    onError: (e) => setError(mensajeDeError(e)),
  })

  function alElegir(e: ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0]
    e.target.value = ''
    if (!f) return
    setArchivo(f)
    setTrabajoId(null)
    analizar.mutate(f)
  }

  const seleccion = (hojas ?? []).filter((h) => elegidas.includes(h.nombre))
  const filas = seleccion.reduce((s, h) => s + h.filas, 0)
  const faltaCliente = seleccion.some((h) => !h.columnas.some((c) => c.clave === 'cliente'))
  // Columnas sin reconocer (con datos) de las hojas elegidas: se pueden guardar como datos adicionales.
  const sinReconocer = useMemo(() => {
    const vistas = new Map<string, number>()
    for (const h of seleccion) {
      for (const c of h.columnas) {
        if (!c.clave && !c.campo && c.llenas > 0) vistas.set(c.titulo, (vistas.get(c.titulo) ?? 0) + c.llenas)
      }
    }
    return [...vistas.entries()]
  }, [seleccion])

  if (trabajoId) {
    return (
      <section className="tarjeta">
        <h2>Carga de {archivo?.name}</h2>
        <Progreso trabajoId={trabajoId} />
        <button className="btn btn-secundario separado" onClick={() => { setTrabajoId(null); setHojas(null); setArchivo(null) }}>
          Cargar otro archivo
        </button>
      </section>
    )
  }

  return (
    <div className="ficha-grilla">
      <section className="tarjeta">
        <h2>Paso 1 · El archivo</h2>
        <p className="suave">
          Sirve la planilla del cliente tal como viene (varias hojas, títulos en cualquier fila) o el formato
          de Cartera. Se reconocen títulos como <em>Rut Deudor, Nombre Deudor, Mail Deudor, Teléfono 1, Saldo Capital,
          ID, Filial, N° Pagaré, Dicom, Etapas de cobranza, Rut Paciente…</em>
        </p>
        <div className="acciones-fila envoltura">
          <label className="btn btn-primario subir-archivo">
            {analizar.isPending ? 'Leyendo…' : archivo ? 'Elegir otro archivo' : 'Elegir el Excel'}
            <input type="file" accept=".xlsx,.xlsm" onChange={alElegir} disabled={analizar.isPending} hidden />
          </label>
          <button className="btn btn-secundario" onClick={() => descargarArchivo('/importar/plantilla')}>
            Descargar formato de Cartera
          </button>
        </div>
        {archivo && <p className="nota">Archivo: {archivo.name}</p>}
        {error && <div className="alerta-error">{error}</div>}

        {hojas && hojas.some((h) => h.sirve) && (
          <>
            <h2 className="paso-titulo">Paso 2 · Qué cargar</h2>
            {hojas.filter((h) => h.sirve).length > 1 && (
              <p className="suave">El archivo trae varias hojas: marca las que quieres cargar.</p>
            )}
            <div className="hojas-carga">
              {hojas.map((h) => (
                <label key={h.nombre} className={`opcion ${elegidas.includes(h.nombre) ? 'elegida' : ''} ${h.sirve ? '' : 'deshabilitada'}`}>
                  <input type="checkbox" disabled={!h.sirve} checked={elegidas.includes(h.nombre)}
                    onChange={() => setElegidas(elegidas.includes(h.nombre)
                      ? elegidas.filter((x) => x !== h.nombre) : [...elegidas, h.nombre])} />
                  <span><strong>{h.nombre}</strong></span>
                  <span className="suave">{h.sirve ? `${h.filas.toLocaleString('es-CL')} filas · títulos en la fila ${h.fila_titulos}` : 'no tiene RUT y nombre del deudor'}</span>
                </label>
              ))}
            </div>

            {seleccion[0] && (
              <div className="columnas-reconocidas">
                <span className="etiqueta-campo">Columnas que se cargan</span>
                <div className="chips">
                  {[...new Set(seleccion[0].columnas.filter((c) => c.clave || c.campo)
                    .map((c) => (c.clave ? nombreColumna(c.clave, c.rol) : c.campo!)))].map((nombre) => (
                    <span key={nombre} className="chip chip-fijo">{nombre}</span>
                  ))}
                </div>
              </div>
            )}

            {sinReconocer.length > 0 && (
              <div className="columnas-reconocidas">
                <span className="etiqueta-campo">Otras columnas: marca las que quieras guardar como datos adicionales</span>
                <div className="chips">
                  {sinReconocer.map(([titulo, llenas]) => (
                    <button key={titulo} type="button" className={`chip ${extras.includes(titulo) ? 'elegido' : ''}`}
                      aria-pressed={extras.includes(titulo)}
                      onClick={() => setExtras(extras.includes(titulo) ? extras.filter((x) => x !== titulo) : [...extras, titulo])}>
                      {titulo} <span className="suave">· {llenas.toLocaleString('es-CL')}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </section>

      {hojas && hojas.some((h) => h.sirve) && (
        <section className="tarjeta">
          <h2>Paso 3 · Cargar</h2>
          <label>
            Cliente {faltaCliente ? '*' : '(el archivo trae la columna)'}
            <select value={clienteId} onChange={(e) => setClienteId(e.target.value)} required={faltaCliente}>
              <option value="">{faltaCliente ? 'Elige el cliente' : 'Según la columna Cliente'}</option>
              {clientes?.map((c) => (
                <option key={c.id} value={c.id}>{c.nombre_fantasia ?? c.razon_social}</option>
              ))}
            </select>
          </label>
          <label className="check">
            <input type="checkbox" checked={crearFiliales} onChange={(e) => setCrearFiliales(e.target.checked)} />
            Crear las filiales que no existan (ej. Santiago, Vitacura)
          </label>
          {esAdmin && (
            <div className="opciones-cuota">
              <label className={`opcion ${!actualizar ? 'elegida' : ''}`}>
                <input type="radio" name="modo" checked={!actualizar} onChange={() => setActualizar(false)} />
                <span><strong>Solo agregar las nuevas</strong></span>
                <span className="suave">las que ya existen (mismo cliente, filial e ID) se saltan</span>
              </label>
              <label className={`opcion ${actualizar ? 'elegida' : ''}`}>
                <input type="radio" name="modo" checked={actualizar} onChange={() => setActualizar(true)} />
                <span><strong>Agregar y actualizar las existentes</strong></span>
                <span className="suave">datos, teléfonos y correos nuevos; cada cambio queda en el historial</span>
              </label>
            </div>
          )}
          <p className="nota">
            Una fila mala no frena las demás. Una cobranza que el cliente marcó como eliminada de cartera queda
            con ese estado; las saldadas, como pagadas.
          </p>
          <button className="btn btn-primario" disabled={cargar.isPending || elegidas.length === 0 || (faltaCliente && !clienteId)}
            onClick={() => cargar.mutate()}>
            {cargar.isPending ? 'Iniciando…' : `Cargar ${filas.toLocaleString('es-CL')} filas`}
          </button>
        </section>
      )}
    </div>
  )
}

// ------------------------------------------------------------ gestiones

function CargaGestiones() {
  const [clienteId, setClienteId] = useState('')
  const [trabajoId, setTrabajoId] = useState<string | null>(null)
  const [nombre, setNombre] = useState('')
  const [error, setError] = useState('')
  const { data: clientes } = useQuery({
    queryKey: ['clientes'],
    queryFn: async () => (await api.get<Cliente[]>('/clientes/')).data,
  })
  const subir = useMutation({
    mutationFn: async (f: File) => {
      const form = new FormData()
      form.append('archivo', f)
      if (clienteId) form.append('cliente_id', clienteId)
      return (await api.post<{ trabajo_id: string }>('/importar/gestiones', form)).data.trabajo_id
    },
    onSuccess: (id) => { setTrabajoId(id); setError('') },
    onError: (e) => setError(mensajeDeError(e)),
  })

  return (
    <div className="ficha-grilla">
      <section className="tarjeta">
        <h2>Gestiones en bloque</h2>
        <p className="suave">Cada fila es una gestión distinta, con su tipo, fecha, texto y quién la hizo:</p>
        <ul className="lista-ayuda">
          <li><strong>Para ubicar el caso</strong> (una basta): <em>N° cobranza</em>, <em>ID cliente</em> (con <em>Filial</em> si el ID se repite entre filiales) o <em>RUT deudor</em> (si tiene una sola cobranza abierta).</li>
          <li><strong>Tipo</strong>: Llamada, WhatsApp, Correo, SMS, Visita, No contesta, Carta, Promesa… (opcional).</li>
          <li><strong>Gestión</strong>: el texto. Si viene solo el tipo, se usa como texto.</li>
          <li><strong>Persona</strong>: nombre o correo del usuario (si falta, quedas tú).</li>
          <li><strong>Fecha</strong> y <strong>Próximo contacto</strong> (opcionales; el próximo contacto sale en la agenda).</li>
        </ul>
        <button className="btn btn-secundario" onClick={() => descargarArchivo('/importar/plantilla-gestiones')}>
          Descargar formato de gestiones
        </button>
      </section>
      <section className="tarjeta">
        {trabajoId ? (
          <>
            <h2>Carga de {nombre}</h2>
            <Progreso trabajoId={trabajoId} />
            <button className="btn btn-secundario separado" onClick={() => setTrabajoId(null)}>Cargar otro archivo</button>
          </>
        ) : (
          <>
            <h2>Subir</h2>
            <label>
              Cliente (si el archivo usa ID cliente y no trae columna Cliente)
              <select value={clienteId} onChange={(e) => setClienteId(e.target.value)}>
                <option value="">Cualquiera</option>
                {clientes?.map((c) => <option key={c.id} value={c.id}>{c.nombre_fantasia ?? c.razon_social}</option>)}
              </select>
            </label>
            <label className="btn btn-primario subir-archivo separado">
              {subir.isPending ? 'Subiendo…' : 'Subir el Excel de gestiones'}
              <input type="file" accept=".xlsx,.xlsm" hidden disabled={subir.isPending} onChange={(e) => {
                const f = e.target.files?.[0]
                e.target.value = ''
                if (f) { setNombre(f.name); subir.mutate(f) }
              }} />
            </label>
            {error && <div className="alerta-error">{error}</div>}
          </>
        )}
      </section>
    </div>
  )
}

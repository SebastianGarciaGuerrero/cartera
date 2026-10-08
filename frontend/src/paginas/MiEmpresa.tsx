import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, mensajeDeError } from '../api/client'
import type { Empresa } from '../api/tipos'
import { LogoEmpresa } from '../componentes/Logo'

// Configuración → Mi empresa (solo admin).
// Estos datos son los que salen impresos en el membrete, la firma y el pie de
// página de los documentos Word (informe de gestiones y estado de cuenta).
// Es la pantalla que hace que el sistema sirva para cualquier empresa sin
// tocar código.

const VACIA: Empresa = {
  razon_social: '', nombre_fantasia: '', rut: '',
  wordmark: '', bajada: '', firma_documentos: '',
  direccion: '', ciudad: '', horario_atencion: '',
  telefonos: '', emails: '', sitio_web: '',
  instrucciones_pago: '',
}

export default function MiEmpresa() {
  const qc = useQueryClient()
  const [form, setForm] = useState<Empresa>(VACIA)
  const [error, setError] = useState('')
  const [guardado, setGuardado] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['empresa'],
    queryFn: async () => (await api.get<Empresa>('/empresa')).data,
  })

  // Cuando llegan los datos del servidor, se cargan al formulario.
  useEffect(() => {
    if (data) setForm({ ...VACIA, ...data })
  }, [data])

  const guardar = useMutation({
    mutationFn: async () => (await api.put<Empresa>('/empresa', form)).data,
    onSuccess: (empresa) => {
      setError('')
      setGuardado(true)
      qc.setQueryData(['empresa'], empresa)
    },
    onError: (err) => { setGuardado(false); setError(mensajeDeError(err)) },
  })

  function campo(nombre: keyof Empresa) {
    return {
      value: (form[nombre] as string | null) ?? '',
      onChange: (e: { target: { value: string } }) => {
        setGuardado(false)
        setForm((f) => ({ ...f, [nombre]: e.target.value }))
      },
    }
  }

  function alEnviar(e: FormEvent) {
    e.preventDefault()
    setError('')
    guardar.mutate()
  }

  if (isLoading) return <div className="pantalla-carga">Cargando datos de la empresa…</div>

  return (
    <>
      <header className="pagina-cabecera">
        <h1>Mi empresa</h1>
      </header>

      <SeccionLogo empresa={data ?? null} />

      <form className="form-finanzas form-alta" onSubmit={alEnviar}>
        <h3>Identidad</h3>
        <div className="fila">
          <label>
            Razón social *
            <input {...campo('razon_social')} maxLength={200} required />
          </label>
          <label>
            Nombre de fantasía
            <input {...campo('nombre_fantasia')} maxLength={100} />
          </label>
          <label>
            RUT
            <input {...campo('rut')} maxLength={12} placeholder="76123456-7" />
          </label>
        </div>

        <h3>Membrete de los documentos</h3>
        <div className="fila">
          <label>
            Encabezado *
            <input {...campo('wordmark')} maxLength={100} required
              placeholder="MI EMPRESA DE COBRANZA" />
          </label>
          <label>
            Bajada
            <input {...campo('bajada')} maxLength={150}
              placeholder="GESTIÓN Y RECUPERO DE CARTERA" />
          </label>
        </div>
        <div className="fila">
          <label>
            Nombre bajo la firma
            <input {...campo('firma_documentos')} maxLength={200}
              placeholder="Mi Empresa de Cobranza SpA" />
          </label>
        </div>
        <p className="nota">
          El encabezado va grande y centrado arriba de cada documento; la bajada
          es la línea chica que va debajo.
        </p>

        <h3>Contacto (pie de las cartas)</h3>
        <div className="fila">
          <label>
            Dirección
            <input {...campo('direccion')} maxLength={200}
              placeholder="Calle 1234, oficina 56" />
          </label>
          <label>
            Ciudad
            <input {...campo('ciudad')} maxLength={100} placeholder="Santiago, Chile" />
          </label>
        </div>
        <div className="fila">
          <label>
            Horario de atención
            <input {...campo('horario_atencion')} maxLength={120}
              placeholder="Atención de 10 a 16 hrs." />
          </label>
          <label>
            Teléfonos
            <input {...campo('telefonos')} maxLength={120} placeholder="(2) 2345 6789" />
          </label>
        </div>
        <div className="fila">
          <label>
            Emails
            <input {...campo('emails')} maxLength={200}
              placeholder="contacto@miempresa.cl" />
          </label>
          <label>
            Sitio web
            <input {...campo('sitio_web')} maxLength={120} placeholder="www.miempresa.cl" />
          </label>
        </div>
        <p className="nota">
          La ciudad también se usa como lugar de emisión de las cartas
          («En Santiago, a 5 de marzo de 2026…»).
        </p>

        <h3>Formas de pago</h3>
        <div className="fila">
          <label>
            Una por línea
            <textarea rows={4} {...campo('instrucciones_pago')}
              placeholder={'Transferencia electrónica a la cuenta del cliente.\nPago presencial en nuestras oficinas.'} />
          </label>
        </div>
        <p className="nota">
          Se imprimen como lista en el estado de cuenta que recibe el deudor.
        </p>

        {error && <div className="alerta-error">{error}</div>}
        {guardado && !guardar.isPending && (
          <p className="nota">Datos guardados. Los próximos documentos ya salen con estos datos.</p>
        )}
        <div className="fila">
          <button className="btn btn-primario" disabled={guardar.isPending}>
            {guardar.isPending ? 'Guardando…' : 'Guardar cambios'}
          </button>
        </div>
      </form>
    </>
  )
}

// Logo de la empresa: sale en los documentos Word y en la barra lateral.
// Sin logo, los documentos muestran un recuadro "LOGO DE LA EMPRESA".
function SeccionLogo({ empresa }: { empresa: Empresa | null }) {
  const qc = useQueryClient()
  const [error, setError] = useState('')
  const subir = useMutation({
    mutationFn: async (archivo: File) => {
      const form = new FormData()
      form.append('archivo', archivo)
      return (await api.put<Empresa>('/empresa/logo', form)).data
    },
    onSuccess: (e) => { setError(''); qc.setQueryData(['empresa'], e); qc.invalidateQueries({ queryKey: ['logo-empresa'] }) },
    onError: (err) => setError(mensajeDeError(err)),
  })
  const quitar = useMutation({
    mutationFn: async () => (await api.delete<Empresa>('/empresa/logo')).data,
    onSuccess: (e) => { qc.setQueryData(['empresa'], e); qc.invalidateQueries({ queryKey: ['logo-empresa'] }) },
  })

  return (
    <section className="form-finanzas form-alta">
      <h3>Logo</h3>
      <div className="logo-zona">
        {empresa?.tiene_logo
          ? <LogoEmpresa tieneLogo version={empresa.logo_actualizado_at} alt="Logo de la empresa" className="logo-vista" />
          : <div className="logo-vacio">LOGO DE LA EMPRESA</div>}
        <div>
          <p className="nota">
            PNG (ideal, con fondo transparente) o JPG, de hasta 1 MB y al menos 600 px de ancho.
            Sale en el encabezado de los acuerdos, informes y estados de cuenta.
          </p>
          <div className="fila">
            <label className="btn btn-secundario">
              {empresa?.tiene_logo ? 'Cambiar logo' : 'Subir logo'}
              <input type="file" accept="image/png,image/jpeg" hidden disabled={!empresa || subir.isPending}
                onChange={(e) => { const f = e.target.files?.[0]; if (f) subir.mutate(f); e.target.value = '' }} />
            </label>
            {empresa?.tiene_logo && (
              <button type="button" className="btn btn-secundario" onClick={() => quitar.mutate()}>Quitar logo</button>
            )}
          </div>
          {!empresa && <p className="suave">Guarda primero los datos de la empresa.</p>}
          {error && <div className="alerta-error">{error}</div>}
        </div>
      </div>
    </section>
  )
}

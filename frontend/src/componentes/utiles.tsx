import type { EstadoCobranza, TipoDocumento } from '../api/tipos'

// Piezas chicas reutilizables: montos en pesos y etiquetas de estado.

const formatoCLP = new Intl.NumberFormat('es-CL', {
  style: 'currency',
  currency: 'CLP',
})

export function Plata({ valor }: { valor: string | number }) {
  return <span className="mono">{formatoCLP.format(Number(valor))}</span>
}

export const NOMBRE_ESTADO: Record<EstadoCobranza, string> = {
  activa: 'Activa',
  acuerdo_pago: 'Acuerdo de pago',
  judicial: 'Judicial',
  pagada: 'Pagada',
  archivada: 'Archivada',
  castigo: 'Castigo',
}

export function EtiquetaEstado({ estado }: { estado: EstadoCobranza }) {
  return <span className={`etiqueta etiqueta-${estado}`}>{NOMBRE_ESTADO[estado]}</span>
}

export function fechaLegible(iso: string | null): string {
  if (!iso) return '—'
  // Una fecha sola ('2026-10-06') el navegador la lee como medianoche UTC,
  // que en Chile es el día anterior: se arma como fecha local.
  const soloFecha = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso)
  const d = soloFecha
    ? new Date(Number(soloFecha[1]), Number(soloFecha[2]) - 1, Number(soloFecha[3]))
    : new Date(iso)
  return d.toLocaleDateString('es-CL', {
    day: '2-digit', month: '2-digit', year: 'numeric',
  })
}

export function fechaHoraLegible(iso: string): string {
  // Formato compacto 24h: "23-07-2026 14:34". Se arma a mano para evitar
  // las variaciones de locale (comas, a.m./p.m.).
  const d = new Date(iso)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getDate())}-${p(d.getMonth() + 1)}-${d.getFullYear()} ` +
    `${p(d.getHours())}:${p(d.getMinutes())}`
}

export const NOMBRE_DOCUMENTO: Record<TipoDocumento, string> = {
  pagare: 'Pagaré',
  factura: 'Factura',
  letra: 'Letra',
  cheque: 'Cheque',
  contrato: 'Contrato',
  boleta: 'Boleta',
  credito: 'Crédito',
  otro: 'Otro',
}

/** Fecha de hoy en la zona horaria del equipo (no UTC): AAAA-MM-DD. */
export function fechaLocal(d: Date = new Date()): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export const MESES_CORTOS = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']

/** $1.234.567 (sin decimales). */
export const clp = (v: number) => '$' + Math.round(v).toLocaleString('es-CL')

/** Monto corto para ejes y tarjetas: $1,2 M · $350 mil. */
export const compacto = (v: number) =>
  v >= 1_000_000 ? `$${(v / 1_000_000).toLocaleString('es-CL', { maximumFractionDigits: 1 })} M`
    : v >= 1000 ? `$${Math.round(v / 1000).toLocaleString('es-CL')} mil` : clp(v)

/** '12345678-5' → '12.345.678-5' */
export function rutConPuntos(rut: string | null | undefined): string {
  if (!rut) return '—'
  const [cuerpo, dv] = rut.split('-')
  return `${Number(cuerpo).toLocaleString('es-CL')}${dv ? '-' + dv : ''}`
}

export const MESES = [
  'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
  'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre',
]

/** Suma meses a una fecha AAAA-MM-DD; si el mes es más corto, queda en su último día. */
export function sumarMeses(iso: string, meses: number): string {
  const [a, m, d] = iso.split('-').map(Number)
  const total = m - 1 + meses
  const anio = a + Math.floor(total / 12)
  const mes = (total % 12) + 1
  const dia = Math.min(d, new Date(anio, mes, 0).getDate())
  return `${anio}-${String(mes).padStart(2, '0')}-${String(dia).padStart(2, '0')}`
}

/** Fecha local de hoy + N días (AAAA-MM-DD). */
export function enDias(n: number): string {
  const d = new Date()
  d.setDate(d.getDate() + n)
  return fechaLocal(d)
}

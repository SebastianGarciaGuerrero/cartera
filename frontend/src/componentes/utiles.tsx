import type { EstadoCobranza, TipoDocumento } from '../api/tipos'

// Piezas chicas reutilizables: montos en pesos y etiquetas de estado.

const formatoCLP = new Intl.NumberFormat('es-CL', {
  style: 'currency',
  currency: 'CLP',
})

export function Plata({ valor }: { valor: string | number }) {
  return <span className="mono">{formatoCLP.format(Number(valor))}</span>
}

const NOMBRE_ESTADO: Record<EstadoCobranza, string> = {
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
  return new Date(iso).toLocaleDateString('es-CL', {
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

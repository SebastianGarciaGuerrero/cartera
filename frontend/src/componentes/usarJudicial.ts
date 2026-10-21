import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Catalogos, TipoTramite, Tribunal } from '../api/judicial'

// Catálogos del módulo judicial: cambian poco, se piden una vez por sesión.

const UNA_HORA = 60 * 60 * 1000

export function useCatalogos() {
  return useQuery({
    queryKey: ['judicial-catalogos'],
    queryFn: async () => (await api.get<Catalogos>('/judicial/catalogos')).data,
    staleTime: UNA_HORA,
  })
}

export function useTribunales() {
  return useQuery({
    queryKey: ['tribunales'],
    queryFn: async () => (await api.get<Tribunal[]>('/judicial/tribunales')).data,
    staleTime: UNA_HORA,
  })
}

export function useTiposTramite() {
  return useQuery({
    queryKey: ['tipos-tramite'],
    queryFn: async () => (await api.get<TipoTramite[]>('/judicial/tipos-tramite')).data,
    staleTime: UNA_HORA,
  })
}

export interface PersonaEquipo { id: string; nombre: string; rol: string }

export function useEquipoJudicial() {
  return useQuery({
    queryKey: ['judicial-equipo'],
    queryFn: async () => (await api.get<PersonaEquipo[]>('/judicial/equipo')).data,
    staleTime: UNA_HORA,
  })
}

/** Procedimiento sugerido según el documento que respalda la deuda. */
export function procedimientoPorDocumento(tipoDocumento: string | null | undefined): string {
  switch (tipoDocumento) {
    case 'cheque': return 'notificacion_cheque'
    case 'factura': return 'notificacion_factura'
    case 'letra': return 'notificacion_letra'
    case 'pagare': return 'ejecutivo'
    default: return 'ejecutivo'
  }
}

/** Días entre hoy y una fecha AAAA-MM-DD (negativo si ya pasó). */
export function diasHasta(iso: string | null): number | null {
  if (!iso) return null
  const [a, m, d] = iso.split('-').map(Number)
  const hoy = new Date()
  const base = new Date(hoy.getFullYear(), hoy.getMonth(), hoy.getDate())
  return Math.round((new Date(a, m - 1, d).getTime() - base.getTime()) / 86_400_000)
}

/** "vence hoy", "vence en 3 días", "venció hace 5 días". */
export function textoPlazo(iso: string | null): string {
  const dias = diasHasta(iso)
  if (dias === null) return 'Sin plazo'
  if (dias === 0) return 'Vence hoy'
  if (dias > 0) return `Vence en ${dias} día${dias === 1 ? '' : 's'}`
  return `Venció hace ${-dias} día${dias === -1 ? '' : 's'}`
}

export function clasePlazo(iso: string | null): string {
  const dias = diasHasta(iso)
  if (dias === null) return 'plazo-sin'
  if (dias < 0) return 'plazo-vencido'
  if (dias <= 3) return 'plazo-cerca'
  return 'plazo-ok'
}

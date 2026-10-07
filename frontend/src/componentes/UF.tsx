import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { ValorUF } from '../api/tipos'

// UF del día desde el backend (que la guarda para todos). Si no se pudo
// obtener, el campo queda para ingresarla a mano.
export function useUF(fecha?: string) {
  return useQuery({
    queryKey: ['uf', fecha ?? 'hoy'],
    queryFn: async () =>
      (await api.get<ValorUF>('/indicadores/uf', { params: fecha ? { fecha } : {} })).data,
    staleTime: 60 * 60 * 1000,
    retry: false,
  })
}

export function formatoUF(valor: string | number): string {
  return Number(valor).toLocaleString('es-CL', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

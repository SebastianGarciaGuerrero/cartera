import type { QueryClient } from '@tanstack/react-query'

/**
 * Después de registrar algo en un caso (gestión, acuerdo, pago): refresca
 * todo lo que puede haber cambiado, incluidos la agenda, la campana de
 * avisos y el panel "Mi seguimiento".
 */
export function refrescarCaso(qc: QueryClient, cobranzaId: string) {
  const claves = [
    ['cobranza', cobranzaId], ['cobranzas'], ['gestiones', cobranzaId], ['acuerdos', cobranzaId],
    ['acuerdo'], ['pagos', cobranzaId], ['agenda'], ['agenda-hoy'], ['avisos'], ['seguimiento'], ['panel'],
  ]
  for (const queryKey of claves) qc.invalidateQueries({ queryKey })
}

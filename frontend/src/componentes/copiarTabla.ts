import type { PlanAcuerdo } from '../api/tipos'

// Copia la tabla de cuotas igual que la calculadora 3-6-9 original: tabla
// HTML con bordes y encabezado celeste (se pega con formato en Word y
// Correo) y, de respaldo, texto separado por tabuladores (para Excel).

const miles = (v: string | number) => Math.round(Number(v)).toLocaleString('es-CL')
const entero = (v: string | number) => Math.round(Number(v))

/** AAAA-MM-DD → DD-MM-AAAA */
const fechaCorta = (iso: string | null) => (iso ? iso.split('-').reverse().join('-') : '')

export async function copiarTablaCuotas(plan: PlanAcuerdo, { fechaPie, cliente }: {
  fechaPie: string | null
  /** Cómo se llama al cliente en esta organización (ej. "clínica"). */
  cliente: string
}): Promise<void> {
  const conGastos = plan.modalidad === 'judicial'
  const conComision = Number(plan.comision_total) > 0
  const conPie = Number(plan.abono_inicial) > 0
  const primera = plan.cuotas[0]
  const pctJudicial = primera && Number(primera.capital) > 0
    ? Math.round(Number(primera.honorarios) / Number(primera.capital) * 100) : 10

  const encabezados = [
    'N° CUOTAS', 'FECHA', `MONTO ABONO ${cliente.toUpperCase()}`, 'INTERÉS',
    conGastos ? `HONORARIOS (${pctJudicial}%)` : 'GASTO COBRANZA',
    ...(conGastos ? ['GASTOS JUDICIALES'] : []),
    ...(conComision ? ['COMISIÓN PAGO EN LÍNEA'] : []),
    'MONTO TOTAL CUOTA',
  ]

  const th = 'border:1px solid #000;background-color:#dce6f1;color:#000000;font-weight:bold;padding:5px 8px;text-align:center;font-size:10pt;font-family:Arial,sans-serif;'
  const td = 'border:1px solid #000;padding:4px 8px;text-align:center;font-size:10pt;font-family:Arial,sans-serif;color:#000000;background-color:#ffffff;'
  const tdNegrita = td + 'font-weight:bold;'

  const filaPie = conPie ? `<tr>
    <td style="${tdNegrita}">PIE</td>
    <td style="${td}">${fechaCorta(fechaPie)}</td>
    <td style="${td}">${miles(plan.capital_pie)}</td>
    <td style="${td}">0</td>
    <td style="${td}">${miles(plan.honorarios_pie)}</td>
    ${conGastos ? `<td style="${td}">0</td>` : ''}
    ${conComision ? `<td style="${td}">0</td>` : ''}
    <td style="${tdNegrita}">${miles(plan.abono_inicial)}</td>
  </tr>` : ''

  const filas = plan.cuotas.map((f, i) => {
    const fondo = `background-color:${i % 2 === 0 ? '#ffffff' : '#f2f2f2'};`
    const c = td + fondo
    const cn = tdNegrita + fondo
    return `<tr>
    <td style="${c}">${f.numero}</td>
    <td style="${c}">${fechaCorta(f.fecha)}</td>
    <td style="${c}">${miles(f.capital)}</td>
    <td style="${c}">${miles(f.intereses)}</td>
    <td style="${c}">${miles(f.honorarios)}</td>
    ${conGastos ? `<td style="${c}">${miles(f.gastos_judiciales)}</td>` : ''}
    ${conComision ? `<td style="${c}">${miles(f.comision)}</td>` : ''}
    <td style="${cn}">${miles(f.total)}</td>
  </tr>`
  }).join('')

  const filaTotal = `<tr>
    <td colspan="${encabezados.length - 1}" style="${tdNegrita}border-top:2px solid #000;text-align:center;">TOTAL</td>
    <td style="${tdNegrita}border-top:2px solid #000;">${miles(plan.gran_total)}</td>
  </tr>`

  const html = `<table style="border-collapse:collapse;width:100%;">
  <thead><tr>${encabezados.map((h) => `<th style="${th}">${h}</th>`).join('')}</tr></thead>
  <tbody>${filaPie}${filas}${filaTotal}</tbody>
</table>`

  const lineaPie = conPie ? [
    'PIE', fechaCorta(fechaPie), entero(plan.capital_pie), 0, entero(plan.honorarios_pie),
    ...(conGastos ? [0] : []), ...(conComision ? [0] : []), entero(plan.abono_inicial),
  ].join('\t') + '\n' : ''
  const texto = encabezados.join('\t') + '\n' + lineaPie +
    plan.cuotas.map((f) => [
      f.numero, fechaCorta(f.fecha), entero(f.capital), entero(f.intereses), entero(f.honorarios),
      ...(conGastos ? [entero(f.gastos_judiciales)] : []), ...(conComision ? [entero(f.comision)] : []),
      entero(f.total),
    ].join('\t')).join('\n') +
    '\nTOTAL\t' + entero(plan.gran_total)

  if (typeof ClipboardItem === 'undefined') {
    await navigator.clipboard.writeText(texto)
    return
  }
  await navigator.clipboard.write([new ClipboardItem({
    'text/html': new Blob([html], { type: 'text/html' }),
    'text/plain': new Blob([texto], { type: 'text/plain' }),
  })])
}

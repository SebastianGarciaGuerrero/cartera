/*
 * SOLO PARA EL MODO DEMO: copia en el navegador de los cálculos del
 * backend (backend/app/calculos.py), para que la demo sin servidor
 * muestre la calculadora. La versión real calcula siempre en el servidor.
 */

const r = (x: number) => Math.floor(x + 0.5)
const TRAMOS: [number | null, number][] = [[10, 0.09], [40, 0.06], [null, 0.03]]

export function honorarios(capital: number, uf: number | null, modalidad: string, pctJudicial = 10) {
  if (modalidad === 'judicial') {
    const hon = capital * pctJudicial / 100
    return {
      modalidad, capital, uf, capital_uf: uf ? capital / uf : null,
      tramos: [{ desde_uf: 0, hasta_uf: null, porcentaje: pctJudicial, monto_base: capital, honorarios: hon }],
      total_honorarios: hon, total_deuda: capital + hon,
    }
  }
  if (!uf) throw new Error('Para honorarios extrajudiciales se necesita el valor de la UF.')
  let restante = capital
  let desde = 0
  const tramos = TRAMOS.map(([ancho, tasa]) => {
    const limite = ancho === null ? restante : Math.min(restante, ancho * uf)
    const t = { desde_uf: desde, hasta_uf: ancho === null ? null : desde + ancho, porcentaje: tasa * 100,
      monto_base: limite, honorarios: limite * tasa }
    restante -= limite
    if (ancho !== null) desde += ancho
    return t
  })
  const total = tramos.reduce((s, t) => s + t.honorarios, 0)
  return { modalidad, capital, uf, capital_uf: capital / uf, tramos, total_honorarios: total, total_deuda: capital + total }
}

export function capitalDesdeAbono(abono: number, uf: number | null, modalidad: string, pctJudicial = 10) {
  if (modalidad === 'judicial') return honorarios(abono / (1 + pctJudicial / 100), uf, modalidad, pctJudicial)
  if (!uf) throw new Error('Para honorarios extrajudiciales se necesita el valor de la UF.')
  let baseCap = 0
  let baseHon = 0
  let capital = 0
  for (const [ancho, tasa] of TRAMOS) {
    if (ancho === null) { capital = baseCap + (abono - baseCap - baseHon) / (1 + tasa); break }
    const a = ancho * uf
    if (abono <= baseCap + baseHon + a * (1 + tasa)) { capital = baseCap + (abono - baseCap - baseHon) / (1 + tasa); break }
    baseCap += a
    baseHon += a * tasa
  }
  return honorarios(capital, uf, 'extrajudicial')
}

function sumarMes(fecha: string, dia: number, i: number): string {
  const [a, m] = fecha.split('-').map(Number)
  const total = m - 1 + i
  const anio = a + Math.floor(total / 12)
  const mes = (total % 12) + 1
  const ultimo = new Date(anio, mes, 0).getDate()
  return `${anio}-${String(mes).padStart(2, '0')}-${String(Math.min(dia, ultimo)).padStart(2, '0')}`
}

const clp = (v: number) => '$' + Math.round(v).toLocaleString('es-CL')

export function acuerdo(d: Record<string, unknown>) {
  const capital = Number(d.capital)
  const n = Number(d.numero_cuotas)
  const tasa = Number(d.tasa_mensual ?? 0)
  const uf = d.uf ? Number(d.uf) : null
  const modalidad = String(d.modalidad ?? 'extrajudicial')
  const pie = Number(d.abono_inicial ?? 0)
  const gastos = modalidad === 'judicial' ? Number(d.gastos_judiciales ?? 0) : 0
  const conComision = Boolean(d.con_comision)
  if (!(capital > 0)) throw new Error('El capital debe ser mayor que cero.')
  if (pie >= capital) throw new Error('El abono inicial debe ser menor que el capital.')
  if (modalidad === 'extrajudicial' && !uf) throw new Error('Para un acuerdo extrajudicial se necesita el valor de la UF.')

  let capPie = 0
  let honPie = 0
  if (pie > 0) {
    capPie = r(capitalDesdeAbono(pie, uf, modalidad).capital)
    honPie = r(pie) - capPie
  }
  const capNuevo = r(capital) - capPie
  const cuotaCap = r(capNuevo / n)
  const interesMes = r(capNuevo * tasa / 100)
  const honMes = r(honorarios(cuotaCap, uf, modalidad).total_honorarios)
  const gastosCuota = gastos > 0 ? r(gastos / n) : 0
  const comisionTotal = conComision ? r(capital * 2.2491 / 100) : 0
  const comisionCuota = conComision ? r(comisionTotal / n) : 0
  const total = cuotaCap + interesMes + honMes + gastosCuota + comisionCuota
  let ajuste = 0
  if (d.redondeo === 'arriba') ajuste = Math.ceil(total / 1000) * 1000 - total
  if (d.redondeo === 'abajo') ajuste = Math.max(Math.floor(total / 1000) * 1000 - total, -interesMes)
  const valor = total + ajuste
  const capUltima = capNuevo - cuotaCap * (n - 1)
  const difCap = capUltima - cuotaCap
  const primera = d.fecha_primera_cuota ? String(d.fecha_primera_cuota) : null
  const diaSig = d.dia_siguientes ? Number(d.dia_siguientes) : primera ? Number(primera.slice(8, 10)) : 1
  const cuotas = Array.from({ length: n }, (_, i) => {
    const ultima = i === n - 1
    return {
      numero: i + 1,
      fecha: primera ? (i === 0 ? primera : sumarMes(primera, diaSig, i)) : null,
      capital: String(ultima ? capUltima : cuotaCap),
      intereses: String((ultima ? interesMes - difCap : interesMes) + ajuste),
      honorarios: String(honMes), gastos_judiciales: String(gastosCuota), comision: String(comisionCuota),
      total: String(valor),
    }
  })
  const totalIntereses = cuotas.reduce((s, c) => s + Number(c.intereses), 0)
  const texto = (pie > 0 ? `Se efectúa un abono inicial (PIE) de ${clp(pie)}. ` : '') +
    `${pie > 0 ? 'El saldo restante' : 'La deuda'} se pagará en ${n} cuota${n > 1 ? 's iguales, mensuales y sucesivas' : ''} de ${clp(valor)}${n > 1 ? ' cada una' : ''}.`
  return {
    modalidad, capital: String(r(capital)), abono_inicial: String(r(pie)), capital_pie: String(capPie),
    honorarios_pie: String(honPie), capital_en_cuotas: String(capNuevo), numero_cuotas: n,
    tasa_mensual: String(tasa), uf: uf ? String(uf) : null, cuota_capital: String(cuotaCap),
    interes_mensual: String(interesMes + ajuste), honorarios_cuota: String(honMes),
    gastos_judiciales: String(gastosCuota * n), comision_pct: conComision ? '2.2491' : '0',
    comision_total: String(comisionCuota * n), ajuste: String(ajuste), valor_cuota: String(valor),
    total_intereses: String(totalIntereses), total_honorarios: String(honPie + honMes * n),
    total_en_cuotas: String(valor * n), gran_total: String(valor * n + r(pie)), cuotas, texto,
  }
}

export function aTexto(h: ReturnType<typeof honorarios>) {
  return {
    ...h,
    capital: String(r(h.capital)),
    uf: h.uf ? String(h.uf) : null,
    capital_uf: h.capital_uf ? String(h.capital_uf.toFixed(4)) : null,
    tramos: h.tramos.filter((t) => t.monto_base > 0 || h.modalidad === 'judicial').map((t) => ({
      desde_uf: String(t.desde_uf), hasta_uf: t.hasta_uf === null ? null : String(t.hasta_uf),
      porcentaje: String(t.porcentaje), monto_base: String(r(t.monto_base)), honorarios: String(r(t.honorarios)),
    })),
    total_honorarios: String(r(h.total_honorarios)),
    total_deuda: String(r(h.total_deuda)),
  }
}

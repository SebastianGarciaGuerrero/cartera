"""
Cálculos de cobranza: honorarios 3-6-9, desglose de abonos y planes de
acuerdo de pago (portado de la calculadora `cobra369`, con Decimal en vez
de float para que los pesos cuadren siempre).

HONORARIOS EXTRAJUDICIALES 3-6-9 (art. 37 Ley 19.496: tope de gastos de
cobranza extrajudicial, por tramos de la deuda expresada en UF):
  - hasta 10 UF            → 9 %
  - de 10 a 50 UF (40 UF)  → 6 %
  - sobre 50 UF            → 3 %
Los tramos se cortan en pesos (10 UF y 40 UF al valor del día), igual que
en las planillas.

JUDICIAL: tasa plana (10 % por defecto, configurable por organización).

Redondeo: a pesos enteros, mitad hacia arriba (igual que Math.round de JS,
para que los resultados coincidan con la calculadora anterior).
"""

import calendar
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
from typing import List, Literal, Optional

Modalidad = Literal["extrajudicial", "judicial"]

# (ancho del tramo en UF o None = el resto, porcentaje)
TRAMOS_369 = [(Decimal(10), Decimal("0.09")), (Decimal(40), Decimal("0.06")), (None, Decimal("0.03"))]
PCT_JUDICIAL_DEFECTO = Decimal("10")
COMISION_FLOW_DEFECTO = Decimal("2.2491")

CERO = Decimal(0)


def redondear(x: Decimal) -> Decimal:
    """Pesos enteros, mitad hacia arriba (= Math.round de JavaScript)."""
    return (Decimal(x) + Decimal("0.5")).to_integral_value(rounding=ROUND_FLOOR)


@dataclass
class Tramo:
    desde_uf: Decimal
    hasta_uf: Optional[Decimal]
    porcentaje: Decimal      # 9, 6, 3 ó 10
    monto_base: Decimal      # parte del capital que cae en el tramo
    honorarios: Decimal


@dataclass
class Honorarios:
    modalidad: Modalidad
    capital: Decimal
    uf: Optional[Decimal]
    capital_uf: Optional[Decimal]
    tramos: List[Tramo]
    total_honorarios: Decimal
    total_deuda: Decimal


def honorarios(capital: Decimal, uf: Optional[Decimal], modalidad: Modalidad = "extrajudicial",
               pct_judicial: Decimal = PCT_JUDICIAL_DEFECTO) -> Honorarios:
    capital = Decimal(capital)
    if modalidad == "judicial":
        pct = Decimal(pct_judicial)
        hon = capital * pct / 100
        return Honorarios(
            modalidad, capital, uf, (capital / uf) if uf else None,
            [Tramo(CERO, None, pct, capital, hon)], hon, capital + hon,
        )
    if not uf or uf <= 0:
        raise ValueError("Para honorarios extrajudiciales se necesita el valor de la UF.")
    uf = Decimal(uf)
    restante = capital
    tramos: List[Tramo] = []
    desde = CERO
    for ancho_uf, tasa in TRAMOS_369:
        limite = restante if ancho_uf is None else min(restante, ancho_uf * uf)
        tramos.append(Tramo(desde, None if ancho_uf is None else desde + ancho_uf,
                            tasa * 100, limite, limite * tasa))
        restante -= limite
        if ancho_uf is not None:
            desde += ancho_uf
    total = sum((t.honorarios for t in tramos), CERO)
    return Honorarios("extrajudicial", capital, uf, capital / uf, tramos, total, capital + total)


def capital_desde_abono(abono: Decimal, uf: Optional[Decimal], modalidad: Modalidad = "extrajudicial",
                        pct_judicial: Decimal = PCT_JUDICIAL_DEFECTO) -> Honorarios:
    """
    Dado lo que pagó el deudor (capital + honorarios), separa cuánto es
    capital. Inversa exacta por tramos (la calculadora anterior lo hacía por
    búsqueda binaria; el resultado es el mismo).
    """
    abono = Decimal(abono)
    if abono <= 0:
        raise ValueError("El abono debe ser mayor que cero.")
    if modalidad == "judicial":
        capital = abono / (1 + Decimal(pct_judicial) / 100)
        return honorarios(capital, uf, "judicial", pct_judicial)
    if not uf or uf <= 0:
        raise ValueError("Para honorarios extrajudiciales se necesita el valor de la UF.")
    uf = Decimal(uf)
    base_capital = CERO   # capital acumulado de los tramos completos
    base_hon = CERO       # honorarios acumulados de esos tramos
    for ancho_uf, tasa in TRAMOS_369:
        if ancho_uf is None:
            capital = base_capital + (abono - base_capital - base_hon) / (1 + tasa)
            break
        ancho = ancho_uf * uf
        tope_abono = base_capital + base_hon + ancho * (1 + tasa)
        if abono <= tope_abono:
            capital = base_capital + (abono - base_capital - base_hon) / (1 + tasa)
            break
        base_capital += ancho
        base_hon += ancho * tasa
    return honorarios(capital, uf, "extrajudicial")


# ============================================================
# Plan de acuerdo de pago
# ============================================================

@dataclass
class FilaCuota:
    numero: int
    fecha: Optional[date]
    capital: Decimal
    intereses: Decimal
    honorarios: Decimal
    gastos_judiciales: Decimal
    comision: Decimal
    total: Decimal


@dataclass
class PlanAcuerdo:
    modalidad: Modalidad
    capital: Decimal
    abono_inicial: Decimal
    capital_pie: Decimal
    honorarios_pie: Decimal
    capital_en_cuotas: Decimal
    numero_cuotas: int
    tasa_mensual: Decimal
    uf: Optional[Decimal]
    cuota_capital: Decimal
    interes_mensual: Decimal
    honorarios_cuota: Decimal
    gastos_judiciales: Decimal
    comision_pct: Decimal
    comision_total: Decimal
    ajuste: Decimal                     # redondeo aplicado al valor cuota (va al interés)
    valor_cuota: Decimal
    total_intereses: Decimal
    total_honorarios: Decimal
    total_en_cuotas: Decimal
    gran_total: Decimal                 # pie + cuotas
    honorarios_tramos: List[Tramo] = field(default_factory=list)
    cuotas: List[FilaCuota] = field(default_factory=list)


def fechas_cuotas(primera: date, numero: int, dia_siguientes: Optional[int] = None) -> List[date]:
    """
    Primera cuota en la fecha indicada; las siguientes el día `dia_siguientes`
    (o el mismo día de la primera) de cada mes; si el mes es más corto, el
    último día del mes.
    """
    dia = dia_siguientes or primera.day
    fechas = [primera]
    anio, mes = primera.year, primera.month
    for _ in range(1, numero):
        mes += 1
        if mes > 12:
            mes, anio = 1, anio + 1
        fechas.append(date(anio, mes, min(dia, calendar.monthrange(anio, mes)[1])))
    return fechas


def calcular_acuerdo(
    capital: Decimal,
    numero_cuotas: int,
    tasa_mensual: Decimal = CERO,
    uf: Optional[Decimal] = None,
    modalidad: Modalidad = "extrajudicial",
    abono_inicial: Decimal = CERO,
    gastos_judiciales: Decimal = CERO,
    con_comision: bool = False,
    comision_pct: Decimal = COMISION_FLOW_DEFECTO,
    pct_judicial: Decimal = PCT_JUDICIAL_DEFECTO,
    redondeo: Optional[Literal["arriba", "abajo"]] = None,
    fecha_primera: Optional[date] = None,
    dia_siguientes: Optional[int] = None,
) -> PlanAcuerdo:
    """
    Cuotas iguales. Interés simple mensual sobre el capital en cuotas;
    honorarios (3-6-9 o judicial) sobre la cuota de capital; gastos
    judiciales y comisión de pago en línea repartidos en las cuotas.

    Todo se lleva en pesos enteros para que las columnas sumen exacto:
    la última cuota absorbe la diferencia de capital y la compensa en el
    interés, así el valor de todas las cuotas es idéntico y el mandante
    recibe el capital completo.
    """
    capital = Decimal(capital)
    abono_inicial = Decimal(abono_inicial or 0)
    tasa_mensual = Decimal(tasa_mensual or 0)
    gastos_judiciales = Decimal(gastos_judiciales or 0) if modalidad == "judicial" else CERO
    n = int(numero_cuotas)
    if capital <= 0:
        raise ValueError("El capital debe ser mayor que cero.")
    if n < 1 or n > 120:
        raise ValueError("El número de cuotas debe estar entre 1 y 120.")
    if tasa_mensual < 0 or tasa_mensual > 10:
        raise ValueError("La tasa mensual debe estar entre 0 % y 10 %.")
    if abono_inicial < 0 or abono_inicial >= capital:
        raise ValueError("El abono inicial debe ser menor que el capital.")
    if modalidad == "extrajudicial" and (not uf or Decimal(uf) <= 0):
        raise ValueError("Para un acuerdo extrajudicial se necesita el valor de la UF.")
    uf = Decimal(uf) if uf else None

    cap_pie = hon_pie = CERO
    if abono_inicial > 0:
        pie = capital_desde_abono(abono_inicial, uf, modalidad, pct_judicial)
        cap_pie = redondear(pie.capital)
        hon_pie = redondear(abono_inicial) - cap_pie

    cap_nuevo = redondear(capital) - cap_pie
    cuota_cap = redondear(cap_nuevo / n)
    interes_mes = redondear(cap_nuevo * tasa_mensual / 100)
    hon_cuota = honorarios(cuota_cap, uf, modalidad, pct_judicial)
    hon_mes = redondear(hon_cuota.total_honorarios)
    gastos_por_cuota = redondear(gastos_judiciales / n) if gastos_judiciales > 0 else CERO
    comision_total = redondear(capital * Decimal(comision_pct) / 100) if con_comision else CERO
    comision_por_cuota = redondear(comision_total / n) if con_comision else CERO

    total_cuota = cuota_cap + interes_mes + hon_mes + gastos_por_cuota + comision_por_cuota

    ajuste = CERO
    if redondeo == "arriba":
        ajuste = (total_cuota / 1000).to_integral_value(rounding=ROUND_CEILING) * 1000 - total_cuota
    elif redondeo == "abajo":
        ajuste = (total_cuota / 1000).to_integral_value(rounding=ROUND_FLOOR) * 1000 - total_cuota
        if interes_mes + ajuste < 0:
            ajuste = -interes_mes  # no puede quedar interés negativo
    valor_cuota = total_cuota + ajuste

    cap_ultima = cap_nuevo - cuota_cap * (n - 1)
    dif_cap = cap_ultima - cuota_cap
    fechas = fechas_cuotas(fecha_primera, n, dia_siguientes) if fecha_primera else [None] * n

    filas = []
    for i in range(n):
        ultima = i == n - 1
        interes = (interes_mes - dif_cap if ultima else interes_mes) + ajuste
        filas.append(FilaCuota(
            numero=i + 1,
            fecha=fechas[i],
            capital=cap_ultima if ultima else cuota_cap,
            intereses=interes,
            honorarios=hon_mes,
            gastos_judiciales=gastos_por_cuota,
            comision=comision_por_cuota,
            total=valor_cuota,
        ))

    total_en_cuotas = valor_cuota * n
    return PlanAcuerdo(
        modalidad=modalidad,
        capital=redondear(capital),
        abono_inicial=redondear(abono_inicial),
        capital_pie=cap_pie,
        honorarios_pie=hon_pie,
        capital_en_cuotas=cap_nuevo,
        numero_cuotas=n,
        tasa_mensual=tasa_mensual,
        uf=uf,
        cuota_capital=cuota_cap,
        interes_mensual=interes_mes + ajuste,
        honorarios_cuota=hon_mes,
        gastos_judiciales=gastos_por_cuota * n,
        comision_pct=Decimal(comision_pct) if con_comision else CERO,
        comision_total=comision_por_cuota * n,
        ajuste=ajuste,
        valor_cuota=valor_cuota,
        total_intereses=sum((f.intereses for f in filas), CERO),
        total_honorarios=hon_pie + hon_mes * n,
        total_en_cuotas=total_en_cuotas,
        gran_total=total_en_cuotas + redondear(abono_inicial),
        honorarios_tramos=hon_cuota.tramos,
        cuotas=filas,
    )


# ============================================================
# Texto del acuerdo (para el documento y el historial)
# ============================================================

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def clp(valor) -> str:
    return "$" + f"{int(valor):,}".replace(",", ".")


def fecha_texto(f: date) -> str:
    return f"{f.day} de {MESES[f.month - 1]} de {f.year}"


def texto_acuerdo(plan: PlanAcuerdo, fecha_pie: Optional[date] = None,
                  dia_siguientes: Optional[int] = None) -> str:
    partes = []
    if plan.abono_inicial > 0:
        cuando = f" con fecha {fecha_texto(fecha_pie)}" if fecha_pie else ""
        partes.append(f"Se efectúa un abono inicial (PIE) de {clp(plan.abono_inicial)}{cuando}.")
    sujeto = "El saldo restante" if plan.abono_inicial > 0 else "La deuda"
    primera = plan.cuotas[0].fecha
    ultima = plan.cuotas[-1].fecha
    if plan.numero_cuotas == 1:
        texto = f"{sujeto} se pagará en 1 cuota de {clp(plan.valor_cuota)}"
        if primera:
            texto += f", con vencimiento el {fecha_texto(primera)}"
        partes.append(texto + ".")
    else:
        texto = (f"{sujeto} se pagará en {plan.numero_cuotas} cuotas iguales, mensuales y "
                 f"sucesivas de {clp(plan.valor_cuota)} cada una")
        if primera and ultima:
            dia = dia_siguientes or primera.day
            texto += (f". La primera cuota vence el {fecha_texto(primera)} y las restantes "
                      f"los días {dia} de cada mes, finalizando el {fecha_texto(ultima)}, "
                      "ambas fechas inclusive")
        partes.append(texto + ".")
    return " ".join(partes)

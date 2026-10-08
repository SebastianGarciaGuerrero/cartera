"""
Operaciones de negocio que se usan desde más de un endpoint: crear un
acuerdo de pago y registrar un pago, cada una con su gestión automática.

Las usan las pantallas de siempre (POST /api/acuerdos, POST /api/pagos) y la
gestión en un paso (POST /api/gestiones/completa). No hacen commit: quien
llama confirma todo junto, así una gestión con acuerdo se guarda entera o
no se guarda.
"""

import calendar
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.indicadores import hoy_chile
from app.models.acuerdo import AcuerdoPago, Cuota
from app.models.cobranza import Cobranza
from app.models.gestion import Gestion, TipoGestion, tipo_de_sistema
from app.models.pago import Pago
from app.models.usuario import Usuario
from app.schemas.acuerdo import AcuerdoCreate
from app.schemas.pago import PagoCreate


def clp(valor) -> str:
    """$1.234.567"""
    return "$" + f"{int(valor):,}".replace(",", ".")


def con_nota(texto: str, nota: Optional[str] = None, canal: Optional[TipoGestion] = None) -> str:
    """Texto automático + por dónde fue el contacto + el comentario de la persona."""
    partes = [texto]
    if canal is not None:
        partes.append(f"Vía: {canal.nombre}.")
    if nota and nota.strip():
        partes.append(nota.strip())
    return "\n".join(partes)


def gestion_automatica(db: Session, cobranza_id, usuario_id, codigo_tipo: str, descripcion: str,
                       fecha_proximo_contacto: Optional[date] = None) -> Gestion:
    """Registra una gestión automática (acuerdo, abono, pagado...) en el historial."""
    tipo = tipo_de_sistema(db, codigo_tipo)
    gestion = Gestion(
        cobranza_id=cobranza_id,
        usuario_id=usuario_id,
        tipo_id=tipo.id if tipo else None,
        descripcion=descripcion,
        fecha_proximo_contacto=fecha_proximo_contacto,
    )
    db.add(gestion)
    return gestion


# ------------------------------------------------------------ acuerdos

def validar_sin_acuerdo_vigente(db: Session, cobranza_id) -> None:
    """Regla: un solo acuerdo vigente por cobranza (400 si ya hay uno)."""
    existe_vigente = (
        db.query(AcuerdoPago)
        .filter(AcuerdoPago.cobranza_id == cobranza_id, AcuerdoPago.estado == "vigente")
        .first()
    )
    if existe_vigente:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "La cobranza ya tiene un acuerdo vigente. Para renegociar, "
                "marca el acuerdo actual como 'renegociado' y luego crea el nuevo."
            )
        )


def sumar_meses(base: date, meses: int) -> date:
    """
    Suma 'meses' a una fecha, ajustando el día si el mes destino es más corto
    (ej. 31-ene + 1 mes → 28/29-feb). Se usa para calcular vencimientos.
    """
    total = base.month - 1 + meses
    anio = base.year + total // 12
    mes = total % 12 + 1
    ultimo_dia = calendar.monthrange(anio, mes)[1]
    return date(anio, mes, min(base.day, ultimo_dia))


def generar_cuotas(acuerdo: AcuerdoPago) -> List[Cuota]:
    """
    Genera las N cuotas del acuerdo repartiendo (monto_total - pie) en partes
    iguales de 2 decimales; el resto de redondeo se absorbe en la última cuota
    para que la suma cuadre exactamente.
    """
    monto_en_cuotas = Decimal(acuerdo.monto_total_acordado) - Decimal(acuerdo.pie or 0)
    if monto_en_cuotas < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El pie no puede ser mayor que el monto total acordado."
        )

    n = acuerdo.numero_cuotas
    base_cuota = (monto_en_cuotas / n).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    cuotas: List[Cuota] = []
    acumulado = Decimal("0.00")
    for i in range(1, n + 1):
        if i < n:
            monto = base_cuota
            acumulado += base_cuota
        else:
            # última cuota: lo que falte para cuadrar el total exacto
            monto = monto_en_cuotas - acumulado
        cuotas.append(Cuota(
            numero_cuota=i,
            monto=monto,
            fecha_vencimiento=sumar_meses(acuerdo.fecha_primera_cuota, i - 1),
        ))
    return cuotas


def crear_acuerdo(db: Session, cobranza: Cobranza, datos: AcuerdoCreate, usuario: Usuario, *,
                  nota: Optional[str] = None, canal: Optional[TipoGestion] = None,
                  fecha_proximo_contacto: Optional[date] = None) -> tuple[AcuerdoPago, Gestion]:
    """
    Crea el acuerdo con sus cuotas (generadas o escritas a mano), deja la
    cobranza en 'acuerdo_pago' y registra UNA gestión con los términos y el
    comentario de quien lo registró. Quien lo registra recibe los avisos de
    las cuotas en su agenda.
    """
    validar_sin_acuerdo_vigente(db, cobranza.id)

    acuerdo = AcuerdoPago(**datos.model_dump(exclude={"cuotas"}), usuario_id=usuario.id)
    if datos.cuotas:
        acuerdo.cuotas = [Cuota(numero_cuota=i, monto=c.monto, fecha_vencimiento=c.fecha_vencimiento)
                          for i, c in enumerate(datos.cuotas, start=1)]
    else:
        acuerdo.cuotas = generar_cuotas(acuerdo)
    acuerdo.fecha_termino = acuerdo.cuotas[-1].fecha_vencimiento
    cobranza.estado = "acuerdo_pago"

    montos = {c.monto for c in acuerdo.cuotas}
    texto = f"ACUERDO DE PAGO: {clp(acuerdo.monto_total_acordado)} en {acuerdo.numero_cuotas} cuota(s)"
    texto += f" de {clp(acuerdo.cuotas[0].monto)}" if len(montos) == 1 else " de montos distintos"
    if Decimal(acuerdo.pie or 0) > 0:
        texto += f", pie de {clp(acuerdo.pie)}"
    texto += (
        f". Primera cuota vence el {acuerdo.cuotas[0].fecha_vencimiento.strftime('%d-%m-%Y')}"
        f", última el {acuerdo.fecha_termino.strftime('%d-%m-%Y')}."
    )
    gestion = gestion_automatica(db, cobranza.id, usuario.id, "acuerdo", con_nota(texto, nota, canal),
                                 fecha_proximo_contacto)
    db.add(acuerdo)
    return acuerdo, gestion


# ------------------------------------------------------------ pagos

def registrar_pago(db: Session, cobranza: Cobranza, datos: PagoCreate, usuario: Usuario) -> tuple[Pago, Gestion]:
    """
    Registra un pago y aplica la cascada (todo en la transacción de quien llama):
      1. SOLO el capital descuenta el saldo de la cobranza (sin bajar de 0).
      2. Pago de cuota → suma a monto_pagado y recalcula su estado.
      3. Todas las cuotas pagadas → acuerdo 'cumplido' y cobranza 'pagada'.
      4. Saldo en 0 (aunque sea abono libre) → cobranza 'pagada'.
    Deja una gestión con el desglose y el comentario (observaciones).
    """
    cuota = None
    if datos.cuota_id is not None:
        cuota = db.query(Cuota).filter(Cuota.id == datos.cuota_id).first()
        if not cuota:
            raise HTTPException(status_code=404, detail=f"Cuota con id {datos.cuota_id} no encontrada")
        if cuota.acuerdo.cobranza_id != cobranza.id:
            raise HTTPException(status_code=400, detail="La cuota indicada no pertenece a esta cobranza.")

    pago = Pago(**datos.model_dump(), usuario_id=usuario.id)
    if pago.fecha_pago is None:
        pago.fecha_pago = hoy_chile()  # no la de la base (UTC: de noche ya es mañana)
    db.add(pago)

    monto = Decimal(datos.monto)
    capital = Decimal(datos.capital)

    # REGLA: SOLO el capital descuenta el saldo (lo que muestra la app).
    # Honorarios/interés/gastos varían con la UF del día y NO descuentan.
    saldo = Decimal(cobranza.monto_actual) - capital
    cobranza.monto_actual = saldo if saldo > 0 else Decimal("0")

    # La cuota se mide contra el monto TOTAL pagado (lo comprometido).
    if cuota is not None:
        cuota.monto_pagado = Decimal(cuota.monto_pagado) + monto
        if cuota.monto_pagado >= Decimal(cuota.monto):
            cuota.estado = "pagada"
        elif cuota.monto_pagado > 0:
            cuota.estado = "pagada_parcial"
        acuerdo = cuota.acuerdo
        if all(c.estado == "pagada" for c in acuerdo.cuotas):
            acuerdo.estado = "cumplido"
            cobranza.estado = "pagada"

    if cobranza.monto_actual == 0:
        cobranza.estado = "pagada"

    # Desglose: solo los conceptos con monto.
    desglose = []
    if capital > 0:
        desglose.append(f"Saldo Capital: {clp(capital)}")
    if datos.honorarios > 0:
        desglose.append(f"Honorarios: {clp(datos.honorarios)}")
    if datos.intereses > 0:
        desglose.append(f"Interés: {clp(datos.intereses)}")
    if datos.gastos_judiciales > 0:
        desglose.append(f"Gastos judiciales: {clp(datos.gastos_judiciales)}")
    encabezado = (
        f"Pago de cuota {cuota.numero_cuota} por un total de {clp(monto)}"
        if cuota is not None
        else f"Se realizó un abono por un total de {clp(monto)}"
    )
    detalle = f" Desglose: {' · '.join(desglose)}." if desglose else ""
    gestion = gestion_automatica(
        db, cobranza.id, usuario.id, "abono",
        con_nota(f"{encabezado}.{detalle} Saldo capital restante: {clp(cobranza.monto_actual)}.",
                 datos.observaciones),
    )
    if cobranza.estado == "pagada":
        gestion_automatica(db, cobranza.id, usuario.id, "pagado",
                           "CUENTA SALDADA. La cobranza queda en estado pagada.")
    return pago, gestion

"""
Endpoints HTTP para acuerdos de pago.

Endpoints:
  GET  /api/acuerdos            → listar (filtrable por cobranza_id / estado)
  GET  /api/acuerdos/{id}       → detalle con el calendario de cuotas
  POST /api/acuerdos            → crear acuerdo + generar cuotas automáticamente
  PUT  /api/acuerdos/{id}       → cambiar SOLO estado / firma (montos inmutables)

Reglas de negocio implementadas aquí:
  - Solo puede haber UN acuerdo 'vigente' por cobranza a la vez.
  - Al crear un acuerdo, las cuotas se generan solas y la cobranza pasa a
    estado 'acuerdo_pago'.
  - Montos y cuotas son inmutables: una renegociación se hace marcando el
    acuerdo viejo como 'renegociado' (vía PUT) y creando uno nuevo.
"""

import calendar
from uuid import UUID
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.security import get_current_user, usuario_autorizado
from app.models.acuerdo import AcuerdoPago, Cuota
from app.models.cobranza import Cobranza
from app.models.gestion import Gestion, tipo_de_sistema
from app.models.usuario import Usuario
from app.schemas.acuerdo import (
    AcuerdoCreate,
    AcuerdoEstadoUpdate,
    AcuerdoResponse,
    AcuerdoDetalle,
)


# dependencies=[...] exige token válido en TODOS los endpoints del router
# y aplica la regla de roles (viewer = solo lectura).
router = APIRouter(
    prefix="/api/acuerdos",
    tags=["Acuerdos de pago"],
    dependencies=[Depends(usuario_autorizado)],
)


def _sumar_meses(base: date, meses: int) -> date:
    """
    Suma 'meses' a una fecha, ajustando el día si el mes destino es más corto
    (ej. 31-ene + 1 mes → 28/29-feb). Se usa para calcular vencimientos.
    """
    total = base.month - 1 + meses
    anio = base.year + total // 12
    mes = total % 12 + 1
    ultimo_dia = calendar.monthrange(anio, mes)[1]
    return date(anio, mes, min(base.day, ultimo_dia))


def _generar_cuotas(acuerdo: AcuerdoPago) -> List[Cuota]:
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
            fecha_vencimiento=_sumar_meses(acuerdo.fecha_primera_cuota, i - 1),
        ))
    return cuotas


@router.get("/", response_model=List[AcuerdoResponse])
def listar_acuerdos(
    cobranza_id: Optional[UUID] = None,
    estado: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """Lista acuerdos, filtrables por cobranza y/o estado."""
    query = db.query(AcuerdoPago)
    if cobranza_id is not None:
        query = query.filter(AcuerdoPago.cobranza_id == cobranza_id)
    if estado is not None:
        query = query.filter(AcuerdoPago.estado == estado)
    return (
        query.order_by(AcuerdoPago.fecha_acuerdo.desc())
        .offset(skip).limit(limit).all()
    )


@router.get("/{acuerdo_id}", response_model=AcuerdoDetalle)
def obtener_acuerdo(acuerdo_id: UUID, db: Session = Depends(get_db)):
    """Detalle de un acuerdo con su calendario de cuotas."""
    acuerdo = db.query(AcuerdoPago).filter(AcuerdoPago.id == acuerdo_id).first()
    if not acuerdo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Acuerdo con id {acuerdo_id} no encontrado"
        )
    return acuerdo


@router.post("/", response_model=AcuerdoDetalle, status_code=status.HTTP_201_CREATED)
def crear_acuerdo(
    acuerdo_data: AcuerdoCreate,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """
    Crea un acuerdo, genera sus cuotas automáticamente y deja la cobranza en
    estado 'acuerdo_pago'. Rechaza si la cobranza ya tiene un acuerdo vigente.
    Quién lo registró (usuario_id) sale del token.
    """
    # 1. La cobranza debe existir.
    cobranza = db.query(Cobranza).filter(Cobranza.id == acuerdo_data.cobranza_id).first()
    if not cobranza:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cobranza con id {acuerdo_data.cobranza_id} no encontrada"
        )

    # 2. Regla: un solo acuerdo vigente por cobranza.
    existe_vigente = (
        db.query(AcuerdoPago)
        .filter(
            AcuerdoPago.cobranza_id == acuerdo_data.cobranza_id,
            AcuerdoPago.estado == "vigente",
        )
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

    # 3. Crear el acuerdo (estado 'vigente' por defecto).
    nuevo_acuerdo = AcuerdoPago(
        **acuerdo_data.model_dump(),
        usuario_id=usuario.id,  # ← del token, no falsificable
    )

    # 4. Generar cuotas y fijar fecha_termino (vencimiento de la última).
    nuevo_acuerdo.cuotas = _generar_cuotas(nuevo_acuerdo)
    nuevo_acuerdo.fecha_termino = nuevo_acuerdo.cuotas[-1].fecha_vencimiento

    # 5. La cobranza pasa a 'acuerdo_pago'.
    cobranza.estado = "acuerdo_pago"

    # 6. Registrar el acuerdo en el historial de gestiones (automático),
    #    con los términos para identificarlo rápido al revisar el historial.
    def clp(v):
        return "$" + f"{int(v):,}".replace(",", ".")

    cuota_ejemplo = nuevo_acuerdo.cuotas[0].monto
    detalle = (
        f"ACUERDO DE PAGO: {clp(nuevo_acuerdo.monto_total_acordado)} en "
        f"{nuevo_acuerdo.numero_cuotas} cuota(s) de {clp(cuota_ejemplo)}"
    )
    if Decimal(nuevo_acuerdo.pie or 0) > 0:
        detalle += f", pie de {clp(nuevo_acuerdo.pie)}"
    detalle += (
        f". Primera cuota vence el {nuevo_acuerdo.fecha_primera_cuota.strftime('%d-%m-%Y')}"
        f", última el {nuevo_acuerdo.fecha_termino.strftime('%d-%m-%Y')}."
    )
    tipo_acuerdo = tipo_de_sistema(db, "acuerdo")
    db.add(Gestion(
        cobranza_id=cobranza.id,
        usuario_id=usuario.id,
        tipo_id=tipo_acuerdo.id if tipo_acuerdo else None,
        descripcion=detalle,
    ))

    try:
        db.add(nuevo_acuerdo)
        db.commit()
        db.refresh(nuevo_acuerdo)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se pudo crear el acuerdo. Verifica que el usuario (usuario_id) exista."
        )

    return nuevo_acuerdo


@router.put("/{acuerdo_id}", response_model=AcuerdoResponse)
def actualizar_estado_acuerdo(
    acuerdo_id: UUID,
    datos: AcuerdoEstadoUpdate,
    db: Session = Depends(get_db)
):
    """
    Actualiza SOLO el estado, la firma del cliente y observaciones de un
    acuerdo. Los montos y las cuotas no se pueden editar (son inmutables).
    """
    acuerdo = db.query(AcuerdoPago).filter(AcuerdoPago.id == acuerdo_id).first()
    if not acuerdo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Acuerdo con id {acuerdo_id} no encontrado"
        )

    for campo, valor in datos.model_dump(exclude_unset=True).items():
        setattr(acuerdo, campo, valor)

    db.commit()
    db.refresh(acuerdo)
    return acuerdo

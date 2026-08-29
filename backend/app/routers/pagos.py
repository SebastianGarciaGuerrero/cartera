"""
Endpoints HTTP para pagos.

Endpoints:
  GET  /api/pagos          → listar (filtros: cobranza_id, cuota_id, rango de fechas)
  GET  /api/pagos/{id}     → obtener uno
  POST /api/pagos          → registrar un pago (con lógica de cascada)

*** Los pagos son INMUTABLES: no hay PUT ni DELETE. ***

CASCADA al registrar un pago (todo en UNA transacción):
  1. Se descuenta SOLO el capital de cobranzas.monto_actual (sin bajar de 0).
  2. Si el pago es de una cuota → se suma a cuotas.monto_pagado y se recalcula
     su estado (pagada / pagada_parcial).
  3. Si con eso TODAS las cuotas del acuerdo quedan pagadas → el acuerdo pasa
     a 'cumplido' y la cobranza a 'pagada'.
  4. Si el saldo de la cobranza llega a 0 (aunque sea pago directo sin cuota)
     → la cobranza pasa a 'pagada'.
"""

from uuid import UUID
from datetime import date
from decimal import Decimal
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.security import get_current_user, usuario_autorizado
from app.models.pago import Pago
from app.models.cobranza import Cobranza
from app.models.acuerdo import Cuota, AcuerdoPago
from app.models.gestion import Gestion, TipoGestion
from app.models.usuario import Usuario
from app.schemas.pago import PagoCreate, PagoResponse


def _clp(valor) -> str:
    """Formatea un monto como pesos chilenos: $1.234.567."""
    return "$" + f"{int(valor):,}".replace(",", ".")


def _gestion_automatica(db: Session, cobranza_id, usuario_id, nombre_tipo: str, descripcion: str):
    """Registra una gestión automática (ej. Abono, Pagado) en el historial."""
    tipo = db.query(TipoGestion).filter(TipoGestion.nombre == nombre_tipo).first()
    db.add(Gestion(
        cobranza_id=cobranza_id,
        usuario_id=usuario_id,
        tipo_id=tipo.id if tipo else None,
        descripcion=descripcion,
    ))


# dependencies=[...] exige token válido en TODOS los endpoints del router
# y aplica la regla de roles (viewer = solo lectura).
router = APIRouter(
    prefix="/api/pagos",
    tags=["Pagos"],
    dependencies=[Depends(usuario_autorizado)],
)


@router.get("/", response_model=List[PagoResponse])
def listar_pagos(
    cobranza_id: Optional[UUID] = None,
    cuota_id: Optional[UUID] = None,
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """
    Lista pagos con filtros. El rango de fechas (desde/hasta) sirve para armar
    el recupero mensual.
    """
    query = db.query(Pago)
    if cobranza_id is not None:
        query = query.filter(Pago.cobranza_id == cobranza_id)
    if cuota_id is not None:
        query = query.filter(Pago.cuota_id == cuota_id)
    if desde is not None:
        query = query.filter(Pago.fecha_pago >= desde)
    if hasta is not None:
        query = query.filter(Pago.fecha_pago <= hasta)
    return query.order_by(Pago.fecha_pago.desc()).offset(skip).limit(limit).all()


@router.get("/{pago_id}", response_model=PagoResponse)
def obtener_pago(pago_id: UUID, db: Session = Depends(get_db)):
    """Obtiene un pago por su UUID."""
    pago = db.query(Pago).filter(Pago.id == pago_id).first()
    if not pago:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pago con id {pago_id} no encontrado"
        )
    return pago


@router.post("/", response_model=PagoResponse, status_code=status.HTTP_201_CREATED)
def registrar_pago(
    pago_data: PagoCreate,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """
    Registra un pago y aplica la cascada. Todo se confirma junto o nada.
    Quién lo registró (usuario_id) sale del token.
    """
    # --- Validaciones previas ---
    cobranza = db.query(Cobranza).filter(Cobranza.id == pago_data.cobranza_id).first()
    if not cobranza:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cobranza con id {pago_data.cobranza_id} no encontrada"
        )

    cuota = None
    if pago_data.cuota_id is not None:
        cuota = db.query(Cuota).filter(Cuota.id == pago_data.cuota_id).first()
        if not cuota:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Cuota con id {pago_data.cuota_id} no encontrada"
            )
        # La cuota debe pertenecer a un acuerdo de ESTA cobranza (coherencia).
        if cuota.acuerdo.cobranza_id != cobranza.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="La cuota indicada no pertenece a esta cobranza."
            )

    # --- Crear el pago ---
    nuevo_pago = Pago(
        **pago_data.model_dump(),
        usuario_id=usuario.id,  # ← del token, no falsificable
    )
    db.add(nuevo_pago)

    monto = Decimal(pago_data.monto)
    capital = Decimal(pago_data.capital)

    # 1. Descontar del saldo de la cobranza (sin bajar de 0).
    # REGLA: SOLO el capital descuenta el saldo capital del cliente (que es lo
    # que muestra la app). Honorarios/interés/gastos varían con la UF del día y
    # NO descuentan. Si no se ingresa capital, el saldo no se mueve.
    saldo = Decimal(cobranza.monto_actual) - capital
    cobranza.monto_actual = saldo if saldo > 0 else Decimal("0")

    # 2. Si el pago es de una cuota, actualizar su monto_pagado y estado.
    #    La cuota se mide contra el monto TOTAL pagado (lo comprometido).
    if cuota is not None:
        cuota.monto_pagado = Decimal(cuota.monto_pagado) + monto
        if cuota.monto_pagado >= Decimal(cuota.monto):
            cuota.estado = "pagada"
        elif cuota.monto_pagado > 0:
            cuota.estado = "pagada_parcial"

        # 3. ¿Quedaron TODAS las cuotas del acuerdo pagadas?
        acuerdo = cuota.acuerdo
        if all(c.estado == "pagada" for c in acuerdo.cuotas):
            acuerdo.estado = "cumplido"
            cobranza.estado = "pagada"

    # 4. Si el saldo llegó a 0, la cobranza está pagada (cubre pago directo).
    if cobranza.monto_actual == 0:
        cobranza.estado = "pagada"

    # 5. Dejar rastro en el historial de gestiones (automático).
    #    Desglose: solo se listan los conceptos con monto; los vacíos se omiten.
    desglose = []
    if capital > 0:
        desglose.append(f"Saldo Capital: {_clp(capital)}")
    if pago_data.honorarios > 0:
        desglose.append(f"Honorarios: {_clp(pago_data.honorarios)}")
    if pago_data.intereses > 0:
        desglose.append(f"Interés: {_clp(pago_data.intereses)}")
    if pago_data.gastos_judiciales > 0:
        desglose.append(f"Gastos judiciales: {_clp(pago_data.gastos_judiciales)}")
    encabezado = (
        f"Pago de cuota {cuota.numero_cuota} por un total de {_clp(monto)}"
        if cuota is not None
        else f"Se realizó un abono por un total de {_clp(monto)}"
    )
    detalle = f" Desglose: {' · '.join(desglose)}." if desglose else ""
    _gestion_automatica(
        db, cobranza.id, usuario.id, "Abono",
        f"{encabezado}.{detalle} "
        f"Saldo capital restante: {_clp(cobranza.monto_actual)}."
    )
    if cobranza.estado == "pagada":
        _gestion_automatica(
            db, cobranza.id, usuario.id, "Pagado",
            "CUENTA SALDADA. La cobranza queda en estado pagada."
        )

    try:
        db.commit()
        db.refresh(nuevo_pago)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se pudo registrar el pago. Verifica que el usuario (usuario_id) exista."
        )

    return nuevo_pago

"""
Endpoints HTTP para gestión de deudores.

Endpoints:
  GET    /api/deudores                  → listar todos
  GET    /api/deudores/buscar?q=...      → buscar por RUT o nombre (ILIKE)
  GET    /api/deudores/{id}              → ficha completa (con contactos)
  POST   /api/deudores                   → crear uno nuevo (con contactos)
  PUT    /api/deudores/{id}              → actualizar uno existente
  POST   /api/deudores/{id}/contactos    → agregar un contacto
  DELETE /api/deudores/contactos/{id}    → soft-delete de un contacto

NOTA: a diferencia de clientes/filiales, la tabla 'deudores' no tiene
columna 'activo' (ver database/init/001_schema.sql). Un deudor es un
registro maestro permanente que agrupa todas sus cobranzas por RUT;
lo que cambia de estado son las cobranzas, no el deudor. Por eso este
router no expone un DELETE / soft delete del deudor. Los contactos SÍ
tienen soft-delete ('activo').
"""

from uuid import UUID
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import String, cast, func, or_, select, text
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.campos import ErrorCampo, validar_datos_extra
from app.database import get_db
from app.security import get_current_user, usuario_autorizado
from app.models.usuario import Usuario
from app.operaciones import cobranza_del_deudor, describir_cambios, registrar_cambio

NOMBRE_CONTACTO = {"telefono": "teléfono", "celular": "celular", "email": "correo",
                   "whatsapp": "WhatsApp", "otro": "contacto"}


def reincidencia(db: Session, organizacion_id, deudor_ids: list) -> dict:
    """
    deudor_id → (reincidente, cobranzas cerradas). Reincidente: tiene una
    cobranza cerrada (pagada, archivada o castigada) y otra que ingresó
    después del cierre. Cada cobranza sigue siendo una cuenta aparte.
    """
    if not deudor_ids:
        return {}
    filas = db.execute(text("""
        SELECT a.deudor_id, count(*) AS cerradas,
               bool_or(EXISTS (
                   SELECT 1 FROM cobranzas b
                   WHERE b.organizacion_id = a.organizacion_id AND b.deudor_id = a.deudor_id
                     AND b.id <> a.id AND b.fecha_ingreso > COALESCE(a.fecha_cierre, a.fecha_ingreso)
               )) AS reincidente
        FROM cobranzas a
        WHERE a.organizacion_id = :org AND a.deudor_id = ANY(:ids)
          AND a.estado IN ('pagada', 'archivada', 'castigo')
        GROUP BY a.deudor_id
    """), {"org": organizacion_id, "ids": list(deudor_ids)}).mappings().all()
    return {f["deudor_id"]: (bool(f["reincidente"]), f["cerradas"]) for f in filas}
from app.models.cobranza import Cobranza
from app.models.deudor import Deudor, ContactoDeudor
from app.schemas.deudor import (
    DeudorCreate,
    DeudorUpdate,
    DeudorResponse,
    DeudorDetalle,
    DeudorBusqueda,
    ContactoCreate,
    ContactoResponse,
)


# Router agrupa endpoints relacionados.
# prefix="/api/deudores" se agrega a todas las rutas de este router.
# tags=["Deudores"] agrupa los endpoints en la documentación /docs
# dependencies=[...] exige token válido en TODOS los endpoints del router
# y aplica la regla de roles (viewer = solo lectura).
router = APIRouter(
    prefix="/api/deudores",
    tags=["Deudores"],
    dependencies=[Depends(usuario_autorizado)],
)


@router.get("/", response_model=List[DeudorResponse])
def listar_deudores(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db)
):
    """
    Lista todos los deudores con paginación.

    - **skip**: cuántos saltar (para paginación)
    - **limit**: cuántos devolver (máximo 100)
    """
    deudores = db.query(Deudor).offset(skip).limit(limit).all()
    return deudores


@router.get("/buscar", response_model=List[DeudorBusqueda])
def buscar_deudores(
    q: str = Query(..., min_length=1, max_length=100,
                   description="RUT, parte del nombre, N° de cobranza o ID cliente"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """
    Busca deudores por RUT o nombre (coincidencia parcial, sin distinguir
    mayúsculas con ILIKE).

    - **q**: texto a buscar. Ej: "garcia", "12345678", "20001" o "SAP-77120".
    """
    q = q.strip()
    patron = f"%{q}%"
    patron_rut = f"%{q.replace('.', '')}%"  # "12.345" encuentra "12345678-5"
    rut = q.replace(".", "").replace("-", "")
    # También por sus cobranzas: N° (parcial) o ID cliente ("77120" → "SAP-77120").
    por_cobranza = select(Cobranza.deudor_id).where(or_(
        cast(Cobranza.numero, String).like(f"%{q}%"), Cobranza.id_externo.ilike(patron)))
    condiciones = [Deudor.rut.ilike(patron_rut), Deudor.nombre.ilike(patron), Deudor.id.in_(por_cobranza)]
    if rut:
        condiciones.append(func.replace(Deudor.rut, "-", "").ilike(f"%{rut}%"))
    deudores = (
        db.query(Deudor)
        .filter(or_(*condiciones))
        .order_by(Deudor.nombre)
        .limit(limit)
        .all()
    )
    resumen = {}
    if deudores:
        abiertas = Cobranza.estado.in_(("activa", "acuerdo_pago", "judicial"))
        filas = (
            db.query(
                Cobranza.deudor_id,
                func.count(Cobranza.id),
                func.count(Cobranza.id).filter(abiertas),
                func.coalesce(func.sum(Cobranza.monto_actual).filter(abiertas), 0),
            )
            .filter(Cobranza.deudor_id.in_([d.id for d in deudores]))
            .group_by(Cobranza.deudor_id).all()
        )
        resumen = {f[0]: f[1:] for f in filas}
    reincide = reincidencia(db, usuario.organizacion_id, [d.id for d in deudores])
    resultado = []
    for d in deudores:
        total, n_abiertas, saldo = resumen.get(d.id, (0, 0, 0))
        item = DeudorBusqueda.model_validate(d)
        item.total_cobranzas, item.cobranzas_abiertas, item.saldo_abierto = total, n_abiertas, float(saldo)
        item.reincidente, item.cobranzas_cerradas = reincide.get(d.id, (False, 0))
        resultado.append(item)
    return resultado


@router.get("/{deudor_id}", response_model=DeudorDetalle)
def obtener_deudor(deudor_id: UUID, db: Session = Depends(get_db),
                   usuario: Usuario = Depends(get_current_user)):
    """
    Obtiene la ficha completa de un deudor por su UUID,
    incluyendo su lista de contactos y si es reincidente.
    """
    deudor = db.get(Deudor, deudor_id)

    if not deudor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Deudor con id {deudor_id} no encontrado"
        )

    ficha = DeudorDetalle.model_validate(deudor)
    ficha.reincidente, ficha.cobranzas_cerradas = reincidencia(
        db, usuario.organizacion_id, [deudor.id]).get(deudor.id, (False, 0))
    return ficha


@router.post("/", response_model=DeudorDetalle, status_code=status.HTTP_201_CREATED)
def crear_deudor(deudor_data: DeudorCreate, db: Session = Depends(get_db)):
    """
    Crea un deudor nuevo, junto con sus contactos (si trae).
    Todo ocurre en una sola transacción: si algo falla, no se crea nada.
    Si ya existe un deudor con el mismo RUT, devuelve error 400.
    """
    # Separamos los contactos del resto de los datos del deudor.
    datos = deudor_data.model_dump()
    contactos = datos.pop("contactos", [])
    try:
        datos["datos_extra"] = validar_datos_extra(db, "deudor", datos.get("datos_extra"))
    except ErrorCampo as e:
        raise HTTPException(status_code=422, detail=str(e))

    nuevo_deudor = Deudor(**datos)
    nuevo_deudor.contactos = [ContactoDeudor(**c) for c in contactos]

    try:
        db.add(nuevo_deudor)
        db.commit()
        db.refresh(nuevo_deudor)  # Refresca para obtener los valores generados (id, timestamps)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ya existe un deudor con RUT {deudor_data.rut}"
        )

    return nuevo_deudor


@router.put("/{deudor_id}", response_model=DeudorResponse)
def actualizar_deudor(
    deudor_id: UUID,
    deudor_data: DeudorUpdate,
    cobranza_id: Optional[UUID] = Query(None, description="Cobranza donde queda la gestión del cambio"),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Actualiza los datos de un deudor existente."""
    deudor = db.get(Deudor, deudor_id)

    if not deudor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Deudor con id {deudor_id} no encontrado"
        )

    # exclude_unset=True hace que solo actualice los campos que el usuario envió
    datos_actualizados = deudor_data.model_dump(exclude_unset=True)
    if "datos_extra" in datos_actualizados:
        try:
            datos_actualizados["datos_extra"] = validar_datos_extra(
                db, "deudor", datos_actualizados["datos_extra"], actuales=deudor.datos_extra
            )
        except ErrorCampo as e:
            raise HTTPException(status_code=422, detail=str(e))

    antes = {campo: getattr(deudor, campo) for campo in datos_actualizados}
    for campo, valor in datos_actualizados.items():
        setattr(deudor, campo, valor)
    detalle = describir_cambios(antes, datos_actualizados, {"en_boletin_comercial": "En DICOM"})
    if detalle:
        registrar_cambio(db, cobranza_del_deudor(db, deudor.id, cobranza_id), usuario.id, "cambio_datos",
                         f"DATOS DEL DEUDOR MODIFICADOS: {detalle}.")

    db.commit()
    db.refresh(deudor)
    return deudor


# ============================================================
# Contactos del deudor
# ============================================================

@router.post(
    "/{deudor_id}/contactos",
    response_model=ContactoResponse,
    status_code=status.HTTP_201_CREATED
)
def agregar_contacto(
    deudor_id: UUID,
    contacto_data: ContactoCreate,
    cobranza_id: Optional[UUID] = Query(None, description="Cobranza donde queda la gestión del cambio"),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Agrega un contacto (teléfono, email, etc.) a un deudor existente."""
    deudor = db.get(Deudor, deudor_id)

    if not deudor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Deudor con id {deudor_id} no encontrado"
        )

    nuevo_contacto = ContactoDeudor(deudor_id=deudor_id, **contacto_data.model_dump())
    db.add(nuevo_contacto)
    registrar_cambio(db, cobranza_del_deudor(db, deudor_id, cobranza_id), usuario.id, "cambio_datos",
                     f"CONTACTO AGREGADO: {NOMBRE_CONTACTO.get(nuevo_contacto.tipo, nuevo_contacto.tipo)} "
                     f"{nuevo_contacto.valor}.")
    db.commit()
    db.refresh(nuevo_contacto)
    return nuevo_contacto


@router.delete("/contactos/{contacto_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_contacto(contacto_id: UUID, db: Session = Depends(get_db),
                      usuario: Usuario = Depends(get_current_user),
                      cobranza_id: Optional[UUID] = Query(None, description="Cobranza donde queda la gestión")):
    """
    Soft-delete de un contacto: marca activo = False, no lo borra de la DB.
    Así se preserva el historial.
    """
    contacto = db.query(ContactoDeudor).filter(ContactoDeudor.id == contacto_id).first()

    if not contacto:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Contacto con id {contacto_id} no encontrado"
        )

    if contacto.activo:
        registrar_cambio(db, cobranza_del_deudor(db, contacto.deudor_id, cobranza_id), usuario.id, "cambio_datos",
                         f"CONTACTO QUITADO: {NOMBRE_CONTACTO.get(contacto.tipo, contacto.tipo)} {contacto.valor}.")
    contacto.activo = False
    db.commit()
    return None

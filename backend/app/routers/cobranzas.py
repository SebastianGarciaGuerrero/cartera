"""
Endpoints HTTP para gestión de cobranzas (el núcleo del sistema).

Endpoints:
  GET  /api/cobranzas            → listar con paginación y filtros
  GET  /api/cobranzas/buscar     → buscar por N° de cobranza, ID cliente, RUT o nombre deudor
  GET  /api/cobranzas/{id}       → ficha completa (cliente, filial, deudor y terceros)
  POST /api/cobranzas            → crear una nueva
  PUT  /api/cobranzas/{id}       → actualizar (numero, cliente_id y deudor_id NO cambian)

NO hay DELETE: una cobranza no se borra. Para "sacarla de la cartera" se
cambia su 'estado' a 'archivada' o 'castigo' vía PUT.

Todo queda limitado a la organización del usuario (app/tenancy.py): un ID
de otra organización responde 404, igual que uno inexistente.
"""

from uuid import UUID
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query, Response
from sqlalchemy import or_, case, cast, func, String, text
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import IntegrityError

from app import ciclo
from app.campos import ErrorCampo, validar_datos_extra
from app.database import get_db
from app.indicadores import hoy_chile
from app.schemas.judicial import CambiarEtapa, CicloVida
from app.models.judicial import DocumentoCobranza
from app.security import get_current_user, usuario_autorizado
from app.operaciones import clp, describir_cambios, registrar_cambio

NOMBRE_DOCUMENTO = {
    "pagare": "Pagaré", "factura": "Factura", "letra": "Letra", "cheque": "Cheque",
    "contrato": "Contrato", "boleta": "Boleta", "credito": "Crédito", "otro": "Documento",
}
NOMBRE_ETAPA = {clave: nombre for clave, nombre, _ in ciclo.PASOS}
CAMPOS_COBRANZA = {
    "id_externo": "ID cliente", "monto_original": "Monto original", "monto_actual": "Saldo",
    "numero_documento": "N° documento", "fecha_vencimiento_documento": "Vencimiento",
    "motivo_cierre": "Motivo de cierre", "datos_extra": "Campos adicionales",
}


def _nombre_documento(doc) -> str:
    return NOMBRE_DOCUMENTO.get(doc.tipo, doc.tipo) + (f" N° {doc.numero}" if doc.numero else "")
from app.permisos import requiere_permiso
from app.models.cliente import Cliente
from app.models.cobranza import Cobranza
from app.models.deudor import Deudor
from app.models.filial import Filial
from app.models.usuario import Usuario
from app.schemas.cobranza import (
    CobranzaCreate,
    CobranzaUpdate,
    CobranzaResponse,
    CobranzaDetalle,
    DocumentoBase,
    DocumentoResponse,
    DocumentoUpdate,
)


# dependencies=[...] exige token válido en TODOS los endpoints del router
# y aplica la regla de roles (viewer = solo lectura).
router = APIRouter(
    prefix="/api/cobranzas",
    tags=["Cobranzas"],
    dependencies=[Depends(usuario_autorizado)],
)


def _404(cobranza_id) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Cobranza con id {cobranza_id} no encontrada",
    )


def _validar_vinculos(db: Session, cliente_id=None, deudor_id=None,
                      filial_id=None, ejecutivo_id=None) -> None:
    """Los vínculos deben existir en la organización (404 claro si no)."""
    if cliente_id is not None and db.get(Cliente, cliente_id) is None:
        raise HTTPException(status_code=404, detail="El cliente indicado no existe")
    if deudor_id is not None and db.get(Deudor, deudor_id) is None:
        raise HTTPException(status_code=404, detail="El deudor indicado no existe")
    if filial_id is not None:
        filial = db.get(Filial, filial_id)
        if filial is None or (cliente_id is not None and filial.cliente_id != cliente_id):
            raise HTTPException(status_code=404, detail="La filial no existe para ese cliente")
    if ejecutivo_id is not None and db.get(Usuario, ejecutivo_id) is None:
        raise HTTPException(status_code=404, detail="El ejecutivo indicado no existe")


@router.get("/", response_model=List[CobranzaResponse])
def listar_cobranzas(
    response: Response,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    cliente_id: Optional[UUID] = None,
    filial_id: Optional[int] = None,
    ejecutivo_id: Optional[UUID] = None,
    deudor_id: Optional[UUID] = None,
    estado: Optional[str] = None,
    etapa: Optional[str] = Query(None, pattern="^(ingreso|extrajudicial|para_demanda|judicial|termino)$"),
    saldo_min: Optional[float] = Query(None, ge=0),
    saldo_max: Optional[float] = Query(None, ge=0),
    db: Session = Depends(get_db)
):
    """
    Lista cobranzas con paginación y filtros opcionales (se combinan con AND).
    El total sin paginar va en el header X-Total-Count.
    """
    query = db.query(Cobranza).options(joinedload(Cobranza.deudor), joinedload(Cobranza.cliente))

    if cliente_id is not None:
        query = query.filter(Cobranza.cliente_id == cliente_id)
    if filial_id is not None:
        query = query.filter(Cobranza.filial_id == filial_id)
    if ejecutivo_id is not None:
        query = query.filter(Cobranza.ejecutivo_id == ejecutivo_id)
    if deudor_id is not None:
        query = query.filter(Cobranza.deudor_id == deudor_id)
    if estado is not None:
        query = query.filter(Cobranza.estado == estado)
    if etapa is not None:
        if etapa == "termino":
            query = query.filter(Cobranza.estado.in_(ciclo.ESTADOS_TERMINALES))
        else:
            query = query.filter(Cobranza.etapa == etapa,
                                 Cobranza.estado.notin_(ciclo.ESTADOS_TERMINALES))
    if saldo_min is not None:
        query = query.filter(Cobranza.monto_actual >= saldo_min)
    if saldo_max is not None:
        query = query.filter(Cobranza.monto_actual <= saldo_max)

    response.headers["X-Total-Count"] = str(query.order_by(None).count())
    return query.order_by(Cobranza.numero).offset(skip).limit(limit).all()


@router.get("/buscar", response_model=List[CobranzaResponse])
def buscar_cobranzas(
    q: str = Query(..., min_length=1, max_length=100,
                   description="N° de cobranza, ID cliente, RUT o nombre del deudor"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    """
    Busca cobranzas por N° de cobranza (coincidencia parcial: '2000'
    encuentra la 20001), ID cliente ('77120' encuentra 'SAP-77120'), RUT
    (con o sin puntos y guion) o nombre del deudor. Primero lo exacto y lo
    que termina en lo escrito; después el resto por N°.
    """
    q = q.strip()
    patron = f"%{q.replace('.', '')}%"
    rut = q.replace(".", "").replace("-", "")
    query = (db.query(Cobranza).join(Deudor, Cobranza.deudor_id == Deudor.id)
             .options(joinedload(Cobranza.deudor), joinedload(Cobranza.cliente)))

    condiciones = [
        cast(Cobranza.numero, String).like(patron),
        Cobranza.id_externo.ilike(patron),
        Deudor.rut.ilike(patron),
        Deudor.nombre.ilike(f"%{q}%"),
    ]
    if rut:
        condiciones.append(func.replace(Deudor.rut, "-", "").ilike(f"%{rut}%"))
    orden = case(
        (cast(Cobranza.numero, String) == q, 0),
        (func.lower(Cobranza.id_externo) == q.lower(), 0),
        (Cobranza.id_externo.ilike(f"%{q}"), 1),
        (func.replace(Deudor.rut, "-", "").ilike(f"{rut}%"), 1),
        else_=2,
    )
    return query.filter(or_(*condiciones)).order_by(orden, Cobranza.numero).limit(limit).all()


@router.get("/resumen-etapas", dependencies=[Depends(requiere_permiso("ver_totales"))])
def resumen_etapas(cliente_id: Optional[UUID] = None, db: Session = Depends(get_db),
                   usuario: Usuario = Depends(get_current_user)):
    """
    La cartera por etapa del ciclo de vida (cantidad y saldo), para el
    tablero de la lista de cobranzas. Las cerradas van en "termino".
    """
    params = {"org": usuario.organizacion_id, "cliente": cliente_id}
    filtro = "AND cliente_id = :cliente" if cliente_id else ""
    filas = db.execute(text(f"""
        SELECT CASE WHEN estado IN ('pagada', 'archivada', 'castigo') THEN 'termino' ELSE etapa END AS etapa,
               count(*) AS cantidad, COALESCE(sum(monto_actual), 0) AS saldo
        FROM cobranzas
        WHERE organizacion_id = :org {filtro}
        GROUP BY 1
    """), params).mappings().all()
    por_etapa = {f["etapa"]: {"cantidad": f["cantidad"], "saldo": f["saldo"]} for f in filas}
    return [{"etapa": e, **por_etapa.get(e, {"cantidad": 0, "saldo": 0})}
            for e in (*ciclo.ETAPAS, "termino")]


@router.get("/{cobranza_id}", response_model=CobranzaDetalle)
def obtener_cobranza(cobranza_id: UUID, db: Session = Depends(get_db)):
    """Ficha completa de una cobranza, con cliente, filial, deudor y terceros."""
    cobranza = db.get(Cobranza, cobranza_id)
    if not cobranza:
        raise _404(cobranza_id)
    return cobranza


@router.post("/", response_model=CobranzaResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(requiere_permiso("cobranzas_crear"))])
def crear_cobranza(cobranza_data: CobranzaCreate, db: Session = Depends(get_db)):
    """
    Crea una cobranza nueva.
    - El N° de cobranza lo asigna PostgreSQL (correlativo de la organización).
    - monto_actual se inicializa igual a monto_original.
    - Si id_externo ya existe para ese cliente, devuelve error 400.
    """
    datos = cobranza_data.model_dump()
    _validar_vinculos(db, datos["cliente_id"], datos["deudor_id"],
                      datos.get("filial_id"), datos.get("ejecutivo_id"))
    try:
        datos["datos_extra"] = validar_datos_extra(
            db, "cobranza", datos.get("datos_extra"), cliente_id=datos["cliente_id"]
        )
    except ErrorCampo as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Regla de negocio: al crear, el saldo actual = la deuda original.
    datos["monto_actual"] = datos["monto_original"]
    nueva_cobranza = Cobranza(**datos)

    try:
        db.add(nueva_cobranza)
        db.commit()
        db.refresh(nueva_cobranza)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ya existe una cobranza con ese ID externo para ese cliente.",
        )

    return nueva_cobranza


@router.put("/{cobranza_id}", response_model=CobranzaResponse)
def actualizar_cobranza(
    cobranza_id: UUID,
    cobranza_data: CobranzaUpdate,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """
    Actualiza una cobranza. El N° de cobranza, el cliente y el deudor NO se
    pueden cambiar (no están en CobranzaUpdate). Aquí se cambia el estado.
    """
    cobranza = db.get(Cobranza, cobranza_id)
    if not cobranza:
        raise _404(cobranza_id)

    cambios = cobranza_data.model_dump(exclude_unset=True)
    _validar_vinculos(db, cliente_id=cobranza.cliente_id,
                      filial_id=cambios.get("filial_id"),
                      ejecutivo_id=cambios.get("ejecutivo_id"))
    if "datos_extra" in cambios:
        try:
            cambios["datos_extra"] = validar_datos_extra(
                db, "cobranza", cambios["datos_extra"],
                cliente_id=cobranza.cliente_id, actuales=cobranza.datos_extra,
            )
        except ErrorCampo as e:
            raise HTTPException(status_code=422, detail=str(e))

    if cambios.get("motivo_cierre") and cambios["motivo_cierre"] not in ciclo.MOTIVOS_CIERRE:
        raise HTTPException(status_code=422, detail="Motivo de cierre desconocido")

    def legibles() -> dict:
        # El ejecutivo y la filial, por su nombre (no por su id).
        valores = {c: getattr(cobranza, c) for c in cambios if c not in ("ejecutivo_id", "filial_id")}
        if "ejecutivo_id" in cambios:
            u = db.get(Usuario, cobranza.ejecutivo_id) if cobranza.ejecutivo_id else None
            valores["Ejecutivo"] = u.nombre if u else None
        if "filial_id" in cambios:
            f = db.get(Filial, cobranza.filial_id) if cobranza.filial_id else None
            valores["Filial"] = f.nombre if f else None
        return valores
    antes = legibles()
    for campo, valor in cambios.items():
        setattr(cobranza, campo, valor)
    detalle = describir_cambios(antes, legibles(), CAMPOS_COBRANZA)
    if detalle:
        registrar_cambio(db, [cobranza.id], usuario.id, "cambio_datos",
                         f"DATOS DE LA COBRANZA MODIFICADOS: {detalle}.")
    # Ciclo de vida: al cerrar queda la fecha; al reabrir se limpia el cierre.
    if "estado" in cambios:
        if cobranza.estado in ciclo.ESTADOS_TERMINALES:
            cobranza.fecha_cierre = cobranza.fecha_cierre or hoy_chile()
            if not cobranza.motivo_cierre:
                cobranza.motivo_cierre = "pagada" if cobranza.estado == "pagada" else "otro"
        else:
            cobranza.fecha_cierre = None
            cobranza.motivo_cierre = None

    try:
        db.commit()
        db.refresh(cobranza)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se pudo actualizar: posible ID externo repetido para el cliente."
        )

    return cobranza


# ------------------------------------------------------------ ciclo de vida

@router.get("/{cobranza_id}/ciclo", response_model=CicloVida)
def ciclo_de_vida(cobranza_id: UUID, db: Session = Depends(get_db)):
    """Etapa actual, pasos de la barra, causas e historial de etapas."""
    cobranza = db.get(Cobranza, cobranza_id)
    if not cobranza:
        raise _404(cobranza_id)
    return ciclo.estado_ciclo(db, cobranza)


@router.post("/{cobranza_id}/etapa", response_model=CicloVida)
def cambiar_etapa(cobranza_id: UUID, datos: CambiarEtapa, db: Session = Depends(get_db),
                  usuario: Usuario = Depends(get_current_user)):
    """
    Mueve una cobranza entre las etapas previas a la demanda (extrajudicial
    ↔ para demanda). A judicial se pasa presentando la demanda.
    """
    cobranza = db.get(Cobranza, cobranza_id)
    if not cobranza:
        raise _404(cobranza_id)
    anterior = cobranza.etapa
    try:
        ciclo.cambiar_etapa(db, cobranza, datos.etapa, usuario.id, datos.motivo)
    except ciclo.ErrorEtapa as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    if cobranza.etapa != anterior:
        motivo = f". Motivo: {datos.motivo.strip()}" if datos.motivo and datos.motivo.strip() else ""
        registrar_cambio(db, [cobranza.id], usuario.id, "etapa",
                         f"CAMBIO DE ETAPA: {NOMBRE_ETAPA.get(anterior, anterior)} → "
                         f"{NOMBRE_ETAPA.get(cobranza.etapa, cobranza.etapa)}{motivo}.")
    db.commit()
    db.refresh(cobranza)
    return ciclo.estado_ciclo(db, cobranza)


# ------------------------------------------------------------ documentos

@router.get("/{cobranza_id}/documentos", response_model=List[DocumentoResponse])
def documentos(cobranza_id: UUID, todos: bool = False, db: Session = Depends(get_db)):
    """Documentos que respaldan la cobranza (los vigentes; todos=true incluye los quitados)."""
    if db.get(Cobranza, cobranza_id) is None:
        raise _404(cobranza_id)
    q = db.query(DocumentoCobranza).filter(DocumentoCobranza.cobranza_id == cobranza_id)
    if not todos:
        q = q.filter(DocumentoCobranza.activo.is_(True))
    return q.order_by(DocumentoCobranza.fecha_vencimiento.nulls_last(), DocumentoCobranza.created_at).all()


@router.post("/{cobranza_id}/documentos", response_model=DocumentoResponse, status_code=status.HTTP_201_CREATED)
def agregar_documento(cobranza_id: UUID, datos: DocumentoBase, db: Session = Depends(get_db),
                      usuario: Usuario = Depends(get_current_user)):
    if db.get(Cobranza, cobranza_id) is None:
        raise _404(cobranza_id)
    doc = DocumentoCobranza(**datos.model_dump(), cobranza_id=cobranza_id, creado_por=usuario.id)
    db.add(doc)
    texto = f"DOCUMENTO AGREGADO: {_nombre_documento(doc)}"
    if doc.monto is not None:
        texto += f", {clp(doc.monto)}"
    if doc.fecha_vencimiento:
        texto += f", vence el {doc.fecha_vencimiento:%d-%m-%Y}"
    registrar_cambio(db, [cobranza_id], usuario.id, "cambio_datos", texto + ".")
    db.commit()
    db.refresh(doc)
    return doc


@router.put("/documentos/{documento_id}", response_model=DocumentoResponse)
def corregir_documento(documento_id: UUID, datos: DocumentoUpdate, db: Session = Depends(get_db),
                       usuario: Usuario = Depends(get_current_user)):
    doc = db.get(DocumentoCobranza, documento_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    cambios = datos.model_dump(exclude_unset=True)
    nombre = _nombre_documento(doc)
    antes = {campo: getattr(doc, campo) for campo in cambios}
    for campo, valor in cambios.items():
        setattr(doc, campo, valor)
    if cambios.get("activo") is False and antes.get("activo") is not False:
        texto = f"DOCUMENTO QUITADO: {nombre}."
    else:
        detalle = describir_cambios({k: v for k, v in antes.items() if k != "activo"},
                                    {k: v for k, v in cambios.items() if k != "activo"})
        texto = f"DOCUMENTO MODIFICADO ({nombre}): {detalle}." if detalle else ""
    if texto:
        registrar_cambio(db, [doc.cobranza_id], usuario.id, "cambio_datos", texto)
    db.commit()
    db.refresh(doc)
    return doc

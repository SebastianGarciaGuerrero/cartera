"""
Carga masiva desde Excel (el motor está en app/carga_masiva.py).

  GET  /api/importar/plantilla            → plantilla de cobranzas (+ una columna
                                            por campo adicional de la organización)
  POST /api/importar/analizar             → vista previa: hojas, filas y qué se
                                            reconoció de cada columna
  POST /api/importar/cobranzas            → carga en segundo plano; responde el
                                            id del trabajo
  GET  /api/importar/plantilla-gestiones  → plantilla de gestiones
  POST /api/importar/gestiones            → carga de gestiones en segundo plano
  GET  /api/importar/trabajos/{id}        → avance y resultado de una carga

Actualizar cobranzas que ya existen (modo "actualizar") es solo para el
administrador: cada cambio queda como gestión en el caso.
"""

import json
from io import BytesIO
from typing import Optional
from uuid import UUID

from fastapi import (APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request,
                     UploadFile, status)
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import carga_masiva, trabajos
from app.config import settings
from app.database import get_db
from app.models.campo_personalizado import CampoPersonalizado
from app.models.cliente import Cliente
from app.models.trabajo import Trabajo
from app.models.usuario import Usuario
from app.permisos import requiere_permiso
from app.security import usuario_autorizado

router = APIRouter(
    prefix="/api/importar",
    tags=["Carga masiva"],
    dependencies=[Depends(usuario_autorizado)],
)

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# (título, obligatorio, ejemplo, ancho)
PLANTILLA_COBRANZAS = [
    ("RUT deudor", True, "12.345.678-5", 14),
    ("Nombre deudor", True, "Juan Pérez Soto", 26),
    ("Teléfono 1", False, "+56 9 1234 5678", 17),
    ("Teléfono 2", False, "", 17),
    ("Email", False, "juan@correo.cl", 24),
    ("Dirección", False, "Av. Siempre Viva 123, depto 4", 28),
    ("Comuna", False, "Providencia", 14),
    ("Ciudad", False, "Santiago", 12),
    ("Cliente", True, "Mandante Ejemplo", 18),
    ("Filial", False, "Casa Matriz", 14),
    ("ID cliente", False, "155001", 12),
    ("Monto deuda", True, 450000, 12),
    ("Tipo documento", False, "pagare", 14),
    ("N° documento", False, "PG-4521", 14),
    ("Vencimiento documento", False, "31-03-2026", 20),
    ("Fecha origen", False, "12-01-2026", 14),
    ("Ejecutivo", False, "", 18),
    ("Estado", False, "", 16),
    ("Observaciones", False, "Ingresado por carga masiva", 30),
]
PLANTILLA_GESTIONES = [
    ("N° cobranza", False, "", 12),
    ("ID cliente", False, "155001", 12),
    ("Filial", False, "", 12),
    ("RUT deudor", False, "", 14),
    ("Fecha", False, "01-07-2026", 12),
    ("Tipo", False, "Llamada", 16),
    ("Gestión", True, "Llamada al deudor, se compromete a pagar el día 5.", 50),
    ("Persona", False, "ana@estudio.cl", 22),
    ("Próximo contacto", False, "05-07-2026", 16),
]


def _plantilla(columnas: list, extras: list, hoja: str, archivo: str):
    wb = Workbook()
    ws = wb.active
    ws.title = hoja
    relleno = PatternFill(start_color="3F3F46", end_color="3F3F46", fill_type="solid")
    for col, (titulo, obligatorio, ejemplo, ancho) in enumerate([*columnas, *extras], start=1):
        celda = ws.cell(row=1, column=col, value=titulo + ("*" if obligatorio else ""))
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = relleno
        ws.column_dimensions[celda.column_letter].width = ancho
        ws.cell(row=2, column=col, value=ejemplo)
    ws.freeze_panes = "A2"
    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return StreamingResponse(buffer, media_type=XLSX_MIME,
                             headers={"Content-Disposition": f'attachment; filename="{archivo}"'})


async def _contenido(archivo: UploadFile) -> bytes:
    if not (archivo.filename or "").lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="El archivo debe ser un Excel .xlsx.")
    maximo = settings.max_archivo_mb * 1024 * 1024
    contenido = await archivo.read(maximo + 1)
    if len(contenido) > maximo:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail=f"El archivo supera {settings.max_archivo_mb} MB. Divídelo en partes.")
    return contenido


def _lista(valor: Optional[str]) -> Optional[list[str]]:
    if not valor:
        return None
    try:
        datos = json.loads(valor)
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="Lista inválida")
    if not isinstance(datos, list) or not all(isinstance(x, str) for x in datos):
        raise HTTPException(status_code=422, detail="Lista inválida")
    return datos


# ------------------------------------------------------------ cobranzas

@router.get("/plantilla")
def descargar_plantilla(db: Session = Depends(get_db)):
    """Plantilla Excel: columnas base + una por cada campo adicional."""
    nombres = {c.id: (c.nombre_fantasia or c.razon_social) for c in db.query(Cliente).all()}
    extras = []
    for campo in (db.query(CampoPersonalizado)
                  .filter(CampoPersonalizado.entidad == "cobranza", CampoPersonalizado.activo.is_(True))
                  .order_by(CampoPersonalizado.orden, CampoPersonalizado.etiqueta)):
        titulo = campo.etiqueta
        if campo.cliente_id is not None:
            titulo += f" (solo {nombres.get(campo.cliente_id, 'un cliente')})"
        extras.append((titulo, campo.obligatorio, "", max(14, len(campo.etiqueta) + 2)))
    return _plantilla(PLANTILLA_COBRANZAS, extras, "Cobranzas", "plantilla_carga_cobranzas.xlsx")


@router.post("/analizar", dependencies=[Depends(requiere_permiso("carga_masiva"))])
async def analizar_archivo(archivo: UploadFile = File(...), db: Session = Depends(get_db)):
    """Qué hojas trae el archivo y qué se reconoce de cada columna (no guarda nada)."""
    contenido = await _contenido(archivo)
    try:
        hojas = carga_masiva.analizar(db, contenido)
    except Exception:
        raise HTTPException(status_code=400, detail="No se pudo leer el archivo. ¿Es un Excel .xlsx válido?")
    return {"hojas": hojas}


class TrabajoCreado(BaseModel):
    trabajo_id: UUID


@router.post("/cobranzas", response_model=TrabajoCreado, status_code=202,
             dependencies=[Depends(requiere_permiso("carga_masiva"))])
async def importar_cobranzas(
    request: Request,
    tareas: BackgroundTasks,
    archivo: UploadFile = File(...),
    cliente_id: Optional[UUID] = Form(None),
    hojas: Optional[str] = Form(None, description='Lista JSON de hojas, ej. ["Santiago"]; vacío = todas las que sirven'),
    actualizar: bool = Form(False),
    crear_filiales: bool = Form(True),
    columnas_extra: Optional[str] = Form(None, description="Lista JSON de títulos a guardar como campos adicionales"),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_autorizado),
):
    if actualizar and usuario.rol_nombre != "admin":
        raise HTTPException(status_code=403, detail="Actualizar cobranzas existentes es solo para el administrador.")
    if cliente_id is not None and db.get(Cliente, cliente_id) is None:
        raise HTTPException(status_code=404, detail="El cliente indicado no existe.")
    contenido = await _contenido(archivo)
    opciones = carga_masiva.OpcionesCarga(
        cliente_id=cliente_id, hojas=_lista(hojas), actualizar=actualizar, crear_filiales=crear_filiales,
        columnas_extra=_lista(columnas_extra) or [], archivo=archivo.filename or "",
    )
    try:
        carga_masiva.preparar_hojas(db, contenido, opciones)  # los problemas del archivo, al tiro
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    trabajo = trabajos.lanzar(
        tareas, db, usuario, request, "carga_cobranzas", opciones.archivo,
        lambda sesion, u, avance: carga_masiva.cargar_cobranzas(sesion, u, contenido, opciones, avance),
    )
    return TrabajoCreado(trabajo_id=trabajo.id)


# ------------------------------------------------------------ gestiones

@router.get("/plantilla-gestiones")
def descargar_plantilla_gestiones():
    return _plantilla(PLANTILLA_GESTIONES, [], "Gestiones", "plantilla_carga_gestiones.xlsx")


@router.post("/gestiones", response_model=TrabajoCreado, status_code=202,
             dependencies=[Depends(requiere_permiso("gestiones_masivas"))])
async def importar_gestiones(
    request: Request,
    tareas: BackgroundTasks,
    archivo: UploadFile = File(...),
    cliente_id: Optional[UUID] = Form(None, description="Cliente de los ID de la planilla (si no trae columna Cliente)"),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_autorizado),
):
    if cliente_id is not None and db.get(Cliente, cliente_id) is None:
        raise HTTPException(status_code=404, detail="El cliente indicado no existe.")
    contenido = await _contenido(archivo)
    nombre = archivo.filename or ""
    trabajo = trabajos.lanzar(
        tareas, db, usuario, request, "carga_gestiones", nombre,
        lambda sesion, u, avance: carga_masiva.cargar_gestiones(sesion, u, contenido, cliente_id, nombre, avance),
    )
    return TrabajoCreado(trabajo_id=trabajo.id)


# ------------------------------------------------------------ avance

class EstadoTrabajo(BaseModel):
    id: UUID
    tipo: str
    estado: str
    archivo: Optional[str] = None
    total: int
    procesadas: int
    resultado: Optional[dict] = None


@router.get("/trabajos/{trabajo_id}", response_model=EstadoTrabajo)
def ver_trabajo(trabajo_id: UUID, db: Session = Depends(get_db)):
    trabajo = db.get(Trabajo, trabajo_id)
    if trabajo is None:
        raise HTTPException(status_code=404, detail="Carga no encontrada")
    trabajos.revisar_cortado(db, trabajo)
    return EstadoTrabajo(id=trabajo.id, tipo=trabajo.tipo, estado=trabajo.estado, archivo=trabajo.archivo,
                         total=trabajo.total, procesadas=trabajo.procesadas, resultado=trabajo.resultado)

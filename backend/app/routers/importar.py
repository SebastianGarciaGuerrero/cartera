"""
Carga masiva desde Excel.

  GET  /api/importar/plantilla → plantilla de cobranzas (incluye una columna
       por cada campo personalizado de la organización).
  POST /api/importar/cobranzas → crea deudor (por RUT) + cobranza por fila.
  GET  /api/importar/plantilla-gestiones → plantilla de gestiones.
  POST /api/importar/gestiones → registra gestiones en bloque sobre cobranzas
       existentes de un cliente (identificadas por su ID cliente).

Reglas:
  - Las columnas se reconocen por su TÍTULO (no por posición): se pueden
    reordenar o quitar las opcionales.
  - El CLIENTE debe existir previamente (por nombre de fantasía, razón social
    o RUT). La filial se busca dentro del cliente (opcional).
  - El deudor se busca por RUT (validado y normalizado): si ya existe se
    reutiliza, no se duplica.
  - Cada fila es independiente: las filas buenas entran aunque otras fallen.
  - Las gestiones cargadas en bloque quedan marcadas es_masivo=True y se
    atribuyen a la persona indicada en la fila (nombre o email de un usuario).
"""

import unicodedata
from io import BytesIO
from uuid import UUID
from decimal import Decimal, InvalidOperation
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill

from app.campos import ErrorCampo, campos_aplicables, convertir_valor
from app.config import settings
from app.database import get_db
from app.rut import normalizar_rut
from app.security import usuario_autorizado
from app.models.cliente import Cliente
from app.models.filial import Filial
from app.models.deudor import Deudor, ContactoDeudor
from app.models.cobranza import Cobranza
from app.models.gestion import Gestion
from app.models.usuario import Usuario


router = APIRouter(
    prefix="/api/importar",
    tags=["Carga masiva"],
    dependencies=[Depends(usuario_autorizado)],
)

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# (título en la plantilla, clave interna, obligatorio, ejemplo, ancho)
COLUMNAS = [
    ("RUT deudor", "rut", True, "12.345.678-5", 14),
    ("Nombre deudor", "nombre", True, "Juan Pérez Soto", 26),
    ("Teléfono", "telefono", False, "+56 9 1234 5678", 18),
    ("Email", "email", False, "juan@correo.cl", 24),
    ("Cliente", "cliente", True, "Mandante Ejemplo", 18),
    ("Filial", "filial", False, "Valparaíso", 14),
    ("ID cliente", "id_externo", False, "155001", 12),
    ("Monto deuda", "monto", True, 450000, 12),
    ("Tipo documento", "tipo_documento", False, "pagare", 14),
    ("N° documento", "numero_documento", False, "PG-4521", 14),
    ("Vencimiento documento", "fecha_vencimiento_documento", False, "2026-03-31", 20),
    ("Fecha origen", "fecha_origen", False, "2026-01-12", 14),
    ("Observaciones", "observaciones", False, "Ingresado por carga masiva", 30),
]

TIPOS_DOCUMENTO = {"pagare", "factura", "letra", "cheque", "contrato", "boleta", "credito", "otro"}


def _normalizar_titulo(texto) -> str:
    """'N° documento*' → 'n documento' (sin tildes, asteriscos ni mayúsculas)."""
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    t = t.replace("*", "").replace("°", "").replace("º", "")
    t = t.split("(")[0]  # quita aclaraciones entre paréntesis
    return " ".join(t.lower().split())


def _texto(valor) -> str:
    return str(valor).strip() if valor is not None else ""


def _fecha(valor):
    if valor in (None, ""):
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(_texto(valor)[:10])
    except ValueError:
        raise ValueError(f"Fecha inválida: {valor!r} (usar AAAA-MM-DD)")


def _plantilla(titulos: list, ejemplo: list, anchos: list, hoja: str, archivo: str):
    wb = Workbook()
    ws = wb.active
    ws.title = hoja
    fill = PatternFill(start_color="3F3F46", end_color="3F3F46", fill_type="solid")
    for col, titulo in enumerate(titulos, start=1):
        celda = ws.cell(row=1, column=col, value=titulo)
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = fill
        ws.column_dimensions[celda.column_letter].width = anchos[col - 1]
    for col, valor in enumerate(ejemplo, start=1):
        ws.cell(row=2, column=col, value=valor)
    ws.freeze_panes = "A2"
    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return StreamingResponse(
        buffer, media_type=XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="{archivo}"'},
    )


async def _leer_excel(archivo: UploadFile):
    if not (archivo.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="El archivo debe ser un Excel .xlsx (usa la plantilla).")
    maximo = settings.max_archivo_mb * 1024 * 1024
    contenido = await archivo.read(maximo + 1)
    if len(contenido) > maximo:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"El archivo supera {settings.max_archivo_mb} MB. Divídelo en partes.",
        )
    try:
        wb = load_workbook(BytesIO(contenido), data_only=True, read_only=True)
    except Exception:
        raise HTTPException(status_code=400, detail="No se pudo leer el archivo. ¿Es un .xlsx válido?")
    return wb.active


@router.get("/plantilla")
def descargar_plantilla(db: Session = Depends(get_db)):
    """Plantilla Excel: columnas base + una por cada campo personalizado."""
    titulos = [t + ("*" if oblig else "") for t, _, oblig, _, _ in COLUMNAS]
    ejemplo = [ej for _, _, _, ej, _ in COLUMNAS]
    anchos = [a for _, _, _, _, a in COLUMNAS]
    nombres_cliente = {c.id: (c.nombre_fantasia or c.razon_social) for c in db.query(Cliente).all()}
    for campo in _todos_los_campos(db):
        titulo = campo.etiqueta + ("*" if campo.obligatorio else "")
        if campo.cliente_id is not None:
            titulo += f" (solo {nombres_cliente.get(campo.cliente_id, 'un cliente')})"
        titulos.append(titulo)
        ejemplo.append("")
        anchos.append(max(14, len(campo.etiqueta) + 2))
    return _plantilla(titulos, ejemplo, anchos, "Cobranzas", "plantilla_carga_cobranzas.xlsx")


def _todos_los_campos(db: Session):
    from app.models.campo_personalizado import CampoPersonalizado
    return (
        db.query(CampoPersonalizado)
        .filter(CampoPersonalizado.entidad == "cobranza", CampoPersonalizado.activo.is_(True))
        .order_by(CampoPersonalizado.orden, CampoPersonalizado.etiqueta)
        .all()
    )


class ResultadoImportacion(BaseModel):
    filas_procesadas: int
    cobranzas_creadas: int
    deudores_nuevos: int
    errores: list  # [{fila, error}]
    columnas_ignoradas: list = []


@router.post("/cobranzas", response_model=ResultadoImportacion)
async def importar_cobranzas(
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Procesa el Excel de carga masiva fila por fila."""
    ws = await _leer_excel(archivo)
    filas_iter = ws.iter_rows(values_only=True)
    try:
        encabezado = next(filas_iter)
    except StopIteration:
        raise HTTPException(status_code=400, detail="El archivo está vacío.")

    # Mapear columnas por título: base o campo personalizado.
    base = {_normalizar_titulo(t): clave for t, clave, _, _, _ in COLUMNAS}
    campos = {_normalizar_titulo(c.etiqueta): c for c in _todos_los_campos(db)}
    indice: dict = {}
    indice_campos: dict = {}
    ignoradas = []
    for i, titulo in enumerate(encabezado or []):
        n = _normalizar_titulo(titulo)
        if not n:
            continue
        if n in base:
            indice[base[n]] = i
        elif n in campos:
            indice_campos[i] = campos[n]
        else:
            ignoradas.append(str(titulo))
    faltan = [t for t, clave, oblig, _, _ in COLUMNAS if oblig and clave not in indice]
    if faltan:
        raise HTTPException(status_code=400, detail=f"Faltan columnas obligatorias: {', '.join(faltan)}")

    # Se guardan valores planos: tras cada commit los objetos ORM expiran y
    # releerlos costaría una consulta por fila.
    clientes = [
        (c.id, c.razon_social, {(c.nombre_fantasia or "").lower(), c.razon_social.lower(), c.rut.lower()})
        for c in db.query(Cliente).filter(Cliente.activo.is_(True)).all()
    ]

    def buscar_cliente(texto: str):
        n = texto.lower()
        for cid, _, nombres in clientes:
            if n in nombres:
                return cid
        try:
            rut = normalizar_rut(texto).lower()
        except ValueError:
            return None
        return next((cid for cid, _, nombres in clientes if rut in nombres), None)

    creadas = deudores_nuevos = filas = 0
    errores = []
    for numero_fila, fila in enumerate(filas_iter, start=2):
        if fila is None or all(v is None or str(v).strip() == "" for v in fila):
            continue
        filas += 1

        def valor(clave):
            i = indice.get(clave)
            return fila[i] if i is not None and i < len(fila) else None

        try:
            rut_crudo, nombre = _texto(valor("rut")), _texto(valor("nombre"))
            if not rut_crudo or not nombre:
                raise ValueError("Falta RUT o nombre del deudor")
            rut = normalizar_rut(rut_crudo)
            nombre_cliente = _texto(valor("cliente"))
            cliente_id = buscar_cliente(nombre_cliente) if nombre_cliente else None
            if cliente_id is None:
                raise ValueError(f"Cliente '{nombre_cliente}' no existe en el sistema")
            try:
                monto = Decimal(str(valor("monto")).replace(".", "").replace(",", ".")
                                if isinstance(valor("monto"), str) else str(valor("monto")))
                if monto <= 0:
                    raise InvalidOperation
            except (InvalidOperation, TypeError):
                raise ValueError(f"Monto inválido: {valor('monto')!r}")
            tipo_documento = _texto(valor("tipo_documento")).lower() or "pagare"
            if tipo_documento not in TIPOS_DOCUMENTO:
                raise ValueError(f"Tipo de documento inválido: '{tipo_documento}' "
                                 f"(usar: {', '.join(sorted(TIPOS_DOCUMENTO))})")

            filial = None
            nombre_filial = _texto(valor("filial"))
            if nombre_filial:
                filial = (
                    db.query(Filial)
                    .filter(Filial.cliente_id == cliente_id, Filial.nombre.ilike(nombre_filial))
                    .first()
                )
                if filial is None:
                    raise ValueError(f"Filial '{nombre_filial}' no existe para {nombre_cliente}")

            datos_extra = {}
            for i, campo in indice_campos.items():
                v = fila[i] if i < len(fila) else None
                if v in (None, ""):
                    continue
                if campo.cliente_id is not None and campo.cliente_id != cliente_id:
                    continue  # campo de otro mandante: se ignora en esta fila
                datos_extra[campo.clave] = convertir_valor(campo, v)
            obligatorios = [c for c in campos_aplicables(db, "cobranza", cliente_id)
                            if c.obligatorio and c.clave not in datos_extra]
            if obligatorios:
                raise ValueError("Falta: " + ", ".join(c.etiqueta for c in obligatorios))

            # --- Deudor: reutilizar por RUT o crear con sus contactos ---
            deudor = db.query(Deudor).filter(Deudor.rut == rut).first()
            if deudor is None:
                deudor = Deudor(rut=rut, nombre=nombre)
                contactos = []
                if _texto(valor("telefono")):
                    contactos.append(ContactoDeudor(tipo="celular", valor=_texto(valor("telefono"))))
                if _texto(valor("email")):
                    contactos.append(ContactoDeudor(tipo="email", valor=_texto(valor("email"))))
                deudor.contactos = contactos
                db.add(deudor)
                db.flush()
                deudores_nuevos += 1

            id_externo = _texto(valor("id_externo")) or None
            db.add(Cobranza(
                cliente_id=cliente_id,
                filial_id=filial.id if filial else None,
                deudor_id=deudor.id,
                id_externo=id_externo,
                monto_original=monto,
                monto_actual=monto,
                tipo_documento=tipo_documento,
                numero_documento=_texto(valor("numero_documento")) or None,
                fecha_vencimiento_documento=_fecha(valor("fecha_vencimiento_documento")),
                fecha_origen=_fecha(valor("fecha_origen")),
                observaciones=_texto(valor("observaciones")) or None,
                datos_extra=datos_extra,
            ))
            db.commit()
            creadas += 1
        except (ValueError, ErrorCampo) as e:
            db.rollback()
            errores.append({"fila": numero_fila, "error": str(e)[:200]})
        except Exception as e:
            db.rollback()
            mensaje = str(e)
            if "uq_cobranza_id_externo" in mensaje:
                mensaje = f"ID cliente '{_texto(valor('id_externo'))}' ya existe para ese cliente"
            else:
                mensaje = "No se pudo guardar la fila (dato inválido o repetido)."
            errores.append({"fila": numero_fila, "error": mensaje})

    return ResultadoImportacion(
        filas_procesadas=filas,
        cobranzas_creadas=creadas,
        deudores_nuevos=deudores_nuevos,
        errores=errores,
        columnas_ignoradas=ignoradas,
    )


# ============================================================
# Carga masiva de GESTIONES
# ============================================================

COLUMNAS_GESTION = ["ID cliente*", "Fecha (AAAA-MM-DD)", "Gestión*", "Persona*"]
EJEMPLO_GESTION = [
    "155001", "2026-07-01", "Llamada al deudor, se compromete a pagar el día 5.", "ana@estudio.cl",
]


@router.get("/plantilla-gestiones")
def descargar_plantilla_gestiones():
    """Plantilla Excel para cargar gestiones en bloque sobre un cliente."""
    return _plantilla(COLUMNAS_GESTION, EJEMPLO_GESTION, [16, 20, 60, 22],
                      "Gestiones", "plantilla_carga_gestiones.xlsx")


class ResultadoGestiones(BaseModel):
    filas_procesadas: int
    gestiones_creadas: int
    errores: list  # [{fila, error}]


@router.post("/gestiones", response_model=ResultadoGestiones)
async def importar_gestiones(
    cliente_id: UUID = Form(..., description="Cliente al que pertenecen los ID de la planilla"),
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Registra gestiones en bloque sobre cobranzas existentes del cliente
    indicado. Cada fila trae el ID cliente de la cobranza, la fecha, el texto
    de la gestión y la persona que la realizó (nombre o email de un usuario).
    """
    cliente = db.get(Cliente, cliente_id)
    if cliente is None:
        raise HTTPException(status_code=404, detail="El cliente indicado no existe.")
    ws = await _leer_excel(archivo)
    id_del_cliente, nombre_del_cliente = cliente.id, cliente.razon_social

    creadas = filas = 0
    errores = []
    usuarios = {}  # nombre o email → id (valores planos: sobreviven a cada commit)
    for u in db.query(Usuario).all():
        usuarios[u.nombre.lower()] = u.id
        usuarios[u.email.lower()] = u.id

    for i, fila in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if fila is None or all(v is None or str(v).strip() == "" for v in fila):
            continue
        filas += 1
        id_cliente = _texto(fila[0])
        fecha_cruda = fila[1] if len(fila) > 1 else None
        gestion = _texto(fila[2]) if len(fila) > 2 else ""
        persona = _texto(fila[3]) if len(fila) > 3 else ""

        try:
            if not id_cliente:
                raise ValueError("Falta el ID cliente")
            if not gestion:
                raise ValueError("Falta el texto de la gestión")
            if not persona:
                raise ValueError("Falta la persona que realizó la gestión")

            cobranza = (
                db.query(Cobranza)
                .filter(Cobranza.cliente_id == id_del_cliente, Cobranza.id_externo == id_cliente)
                .first()
            )
            if cobranza is None:
                raise ValueError(
                    f"No existe una cobranza con ID cliente '{id_cliente}' en {nombre_del_cliente}"
                )
            usuario_id = usuarios.get(persona.lower())
            if usuario_id is None:
                raise ValueError(f"La persona '{persona}' no es un usuario del sistema")

            fecha = None
            if fecha_cruda:
                if isinstance(fecha_cruda, datetime):
                    fecha = fecha_cruda
                elif isinstance(fecha_cruda, date):
                    fecha = datetime(fecha_cruda.year, fecha_cruda.month, fecha_cruda.day)
                else:
                    fecha = datetime.fromisoformat(_texto(fecha_cruda))

            gestion_obj = Gestion(
                cobranza_id=cobranza.id,
                usuario_id=usuario_id,
                descripcion=gestion,
                es_masivo=True,
            )
            if fecha is not None:
                gestion_obj.fecha_gestion = fecha
            db.add(gestion_obj)
            db.commit()
            creadas += 1
        except ValueError as e:
            db.rollback()
            errores.append({"fila": i, "error": str(e)[:200]})
        except Exception:
            db.rollback()
            errores.append({"fila": i, "error": "No se pudo guardar la fila."})

    return ResultadoGestiones(filas_procesadas=filas, gestiones_creadas=creadas, errores=errores)

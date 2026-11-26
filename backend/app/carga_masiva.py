"""
Carga masiva desde Excel: el motor (los endpoints están en routers/importar.py).

Cobranzas:
  - Reconoce las columnas por su TÍTULO, con sinónimos ("Rut Deudor",
    "Mail Deudor", "Saldo Capital", "N° Pagaré"…), y encuentra sola la fila
    de títulos (puede haber filas de grupos arriba) en cada hoja.
  - Varias hojas en un archivo (p. ej. una por filial).
  - Deudor por RUT (no se duplica); sus teléfonos y correos nuevos se
    agregan. Columnas de un tercero ("Rut Paciente", "Teléfono aval"…) crean
    o reutilizan el tercero con ese rol; si es la misma persona que el
    deudor, sus contactos van al deudor.
  - Columnas no reconocidas: se pueden guardar como campos adicionales.
  - Modo actualizar (solo admin): una cobranza que ya existe (mismo cliente,
    filial e ID cliente) se actualiza en vez de saltarse, y el cambio queda
    como gestión.
Gestiones: cada fila identifica su cobranza por N° de cobranza, ID cliente
(y filial) o RUT del deudor, con su tipo, fecha, persona y próximo contacto.

Cada fila es independiente (punto de guardado propio): una mala no frena
las demás. Se confirma cada LOTE filas y se informa el avance.
"""

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Callable, Optional
from uuid import UUID

import openpyxl.worksheet._reader as _lector_excel
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from sqlalchemy.orm import Session, selectinload

from app import ciclo
from app.campos import ErrorCampo, campos_aplicables, convertir_valor
from app.indicadores import hoy_chile
from app.models.campo_personalizado import CampoPersonalizado
from app.models.cliente import Cliente
from app.models.cobranza import Cobranza
from app.models.deudor import ContactoDeudor, Deudor
from app.models.filial import Filial
from app.models.gestion import Gestion, TipoGestion, tipo_de_sistema
from app.models.pago import PAGO_VIGENTE, Pago
from app.models.tercero import CobranzaTercero, ContactoTercero, Tercero
from app.models.usuario import Usuario
from app.operaciones import ABIERTAS, describir_cambios, registrar_cambio
from app.rut import normalizar_rut

LOTE = 200
MAX_ERRORES = 1000
# Filas con error que se devuelven en el Excel para corregir (con sus datos).
MAX_CORRECCION = 5000
# Columna con el motivo en el Excel para corregir: al volver a subirlo se ignora.
TITULO_ERROR = "Motivo del error"
# Título de la columna que se agrega al Excel para corregir cuando la planilla no la traía.
TITULO_CLAVE = {
    "rut": "RUT deudor", "nombre": "Nombre deudor", "monto": "Saldo capital", "cliente": "Cliente",
    "filial": "Filial", "id_externo": "ID", "tipo_documento": "Tipo documento", "t_rut": "RUT paciente",
    "t_nombre": "Nombre paciente", "numero": "N° cobranza", "tipo": "Tipo", "descripcion": "Gestión",
    "persona": "Persona",
}


class ErrorFila(ValueError):
    """
    Error de una fila, con las columnas que hay que completar o corregir (se
    marcan en amarillo en el Excel para corregir). `campos`: claves internas
    ("rut", "monto"…); con "?" delante solo se marca si la planilla trae la
    columna. `extras`: (índice de columna o None, título) de campos adicionales.
    """

    def __init__(self, mensaje: str, *campos: str, extras: tuple = ()):
        super().__init__(mensaje)
        self.campos = campos
        self.extras = extras


# ------------------------------------------------------------ lectura

# Un teléfono guardado en una celda con formato de fecha (912345678) no es
# una fecha válida: openpyxl lo marcaría como error. Se devuelve el número.
_desde_excel = _lector_excel.from_excel


def _fecha_o_numero(valor, *args, **kwargs):
    try:
        return _desde_excel(valor, *args, **kwargs)
    except (OverflowError, ValueError):
        return valor


_lector_excel.from_excel = _fecha_o_numero


def abrir_libro(contenido: bytes):
    return load_workbook(BytesIO(contenido), data_only=True, read_only=True)


def normalizar(texto) -> str:
    """'N° Pagaré (fecha)*' → 'n pagare' (sin tildes, signos, paréntesis ni mayúsculas)."""
    t = str(texto or "").split("(")[0]
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9@]+", " ", t)
    return " ".join(t.split())


def texto(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    if isinstance(valor, datetime):
        return valor.date().isoformat()
    return str(valor).strip()


def fecha(valor) -> Optional[date]:
    """Fecha de una celda; None si está vacía o no se entiende."""
    if valor in (None, ""):
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    t = texto(valor)[:10]
    for formato in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(t, formato).date()
        except ValueError:
            continue
    return None


def monto(valor) -> Optional[Decimal]:
    if valor in (None, ""):
        return None
    if isinstance(valor, (int, float, Decimal)):
        return Decimal(str(valor)).quantize(Decimal("0.01"))
    t = texto(valor).replace("$", "").replace(" ", "")
    if "," in t:  # 1.234,50 → 1234.50
        t = t.replace(".", "").replace(",", ".")
    elif t.count(".") > 1 or re.fullmatch(r"\d{1,3}(\.\d{3})+", t):
        t = t.replace(".", "")
    try:
        return Decimal(t).quantize(Decimal("0.01"))
    except InvalidOperation:
        raise ValueError(f"Monto inválido: {valor!r}")


def si_no(valor) -> Optional[bool]:
    t = normalizar(valor)
    if t in ("si", "s", "true", "verdadero", "1", "x", "dicom"):
        return True
    if t in ("no", "n", "false", "falso", "0"):
        return False
    return None


def telefono(valor) -> Optional[tuple[str, str, str]]:
    """→ (tipo, valor legible, clave para no repetir) o None si no es un teléfono."""
    digitos = re.sub(r"\D", "", texto(valor))
    if digitos.startswith("56") and len(digitos) == 11:
        digitos = digitos[2:]
    if len(digitos) < 8 or len(digitos) > 12:
        return None
    if len(digitos) == 9 and digitos[0] == "9":
        return "celular", f"+56 9 {digitos[1:5]} {digitos[5:]}", digitos
    if len(digitos) == 9:
        return "telefono", f"+56 {digitos[0]} {digitos[1:5]} {digitos[5:]}", digitos
    return "telefono", digitos, digitos


EMAIL = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[a-z]{2,}$", re.I)


def correos(valor) -> list[str]:
    return [c.lower() for c in re.split(r"[;,\s]+", texto(valor)) if EMAIL.match(c)]


# ------------------------------------------------------------ columnas

# Columnas de la cobranza: clave → títulos aceptados (normalizados), en orden
# de preferencia si un archivo trae más de uno ("Saldo Capital" y "Monto").
COLUMNAS_COBRANZA: dict[str, list[str]] = {
    "cliente": ["cliente", "mandante"],
    "filial": ["filial", "sucursal"],
    "id_externo": ["id cliente", "id", "id cuenta", "n cuenta", "numero cuenta", "numero de cuenta", "cuenta"],
    "monto": ["monto deuda", "monto", "saldo capital", "deuda", "capital adeudado", "saldo"],
    "tipo_documento": ["tipo documento", "tipo de documento"],
    "numero_documento": ["n documento", "numero documento", "n de documento", "numero de documento"],
    "n_pagare": ["n pagare", "numero pagare", "nro pagare", "pagare"],
    "n_factura": ["n factura", "numero factura", "nro factura", "factura"],
    "n_cheque": ["n cheque", "numero cheque", "nro cheque", "cheque"],
    "n_letra": ["n letra", "numero letra", "nro letra", "letra"],
    "fecha_vencimiento_documento": ["vencimiento documento", "fecha vencimiento documento", "fecha vencimiento",
                                    "fecha vencimiento pagare", "vencimiento"],
    "fecha_origen": ["fecha origen", "fecha deuda", "fecha emision"],
    "fecha_ingreso": ["fecha ingreso cobranza", "fecha asignacion", "fecha envio a empresa de cobranza",
                      "fecha envio cobranza"],
    "fecha_traspaso": ["fecha traspaso"],
    "dicom": ["dicom", "boletin comercial", "en dicom"],
    "estado": ["estado", "estado cobranza", "estado de cobranza", "etapa", "etapas de cobranza",
               "etapa de cobranza", "etapa cobranza"],
    "ejecutivo": ["ejecutivo", "ejecutiva", "ejecutivo asignado", "ejecutiva asignada", "asignado a", "gestor"],
    "observaciones": ["observaciones", "observacion", "comentario", "comentarios", "notas"],
    "autorizacion_firma": ["autorizacion de firma de pagare", "autorizacion firma pagare", "autorizacion firma"],
    "comprobante_envio": ["comprobante chilexpress o correos de chile", "comprobante envio", "n comprobante envio"],
    "fecha_envio_documentos": ["fecha envio documentos fisico", "fecha envio documentos"],
}
TIPO_POR_COLUMNA = {"n_pagare": "pagare", "n_factura": "factura", "n_cheque": "cheque", "n_letra": "letra"}
TIPOS_DOCUMENTO = {"pagare", "factura", "letra", "cheque", "contrato", "boleta", "credito", "otro"}

# Datos de una persona (deudor o tercero).
CAMPOS_PERSONA = {
    "rut": {"rut"}, "nombre": {"nombre", "nombre completo", "razon social"},
    "direccion": {"direccion", "domicilio"}, "comuna": {"comuna"}, "ciudad": {"ciudad"}, "region": {"region"},
}
PATRON_TELEFONO = re.compile(r"^(telefono|fono|celular|movil|whatsapp)( \d+)?$")
PATRON_EMAIL = re.compile(r"^(email|e mail|mail|correo|correo electronico)( \d+)?$")
ROLES_TERCERO = ("paciente", "aval", "codeudor")
RELLENO_PERSONA = {"deudor", "del", "de", "titular", *ROLES_TERCERO}
MULTIPLES = {"telefono", "email", "t_telefono", "t_email"}


@dataclass
class Columna:
    indice: int
    titulo: str
    clave: Optional[str] = None          # interna (rut, monto, t_telefono…) o None
    campo: Optional[CampoPersonalizado] = None  # campo adicional existente con ese título
    rol: Optional[str] = None            # rol del tercero (paciente, aval…)


def reconocer(titulo) -> tuple[Optional[str], Optional[str], int]:
    """Título → (clave, rol de tercero, prioridad). Clave None = no reconocida."""
    t = normalizar(titulo)
    if not t:
        return None, None, 0
    for clave, titulos in COLUMNAS_COBRANZA.items():
        if t in titulos:
            return clave, None, titulos.index(t)
    palabras = t.split()
    rol = next((r for r in ROLES_TERCERO if r in palabras), None)
    if rol is None and "deudor" not in palabras and t not in ("rut", "nombre", "deudor") \
            and not PATRON_TELEFONO.match(t) and not PATRON_EMAIL.match(t) \
            and t not in {x for v in CAMPOS_PERSONA.values() for x in v}:
        return None, None, 0
    base = " ".join(p for p in palabras if p not in RELLENO_PERSONA) or ("nombre" if t == "deudor" else "")
    prefijo = "t_" if rol else ""
    if PATRON_TELEFONO.match(base):
        return prefijo + "telefono", rol, 0
    if PATRON_EMAIL.match(base):
        return prefijo + "email", rol, 0
    for campo, titulos in CAMPOS_PERSONA.items():
        if base in titulos:
            return prefijo + campo, rol, 0
    return None, None, 0


@dataclass
class Hoja:
    nombre: str
    fila_titulos: int                    # 1 = primera fila de Excel
    columnas: list[Columna]
    filas: list[tuple[int, tuple]]       # (n° de fila en Excel, valores)

    @property
    def claves(self) -> set:
        return {c.clave for c in self.columnas if c.clave}

    @property
    def con_paciente(self) -> bool:
        """¿Trae columnas del paciente? (sirven de deudor cuando faltan sus datos)."""
        return any(c.rol == "paciente" for c in self.columnas)

    def tiene(self, clave: str) -> bool:
        """RUT y nombre del deudor pueden venir solo del paciente."""
        return clave in self.claves or (
            clave in ("rut", "nombre") and self.con_paciente and f"t_{clave}" in self.claves)

    @property
    def sirve(self) -> bool:
        return self.tiene("rut") and self.tiene("nombre")

    def titulos(self) -> list:
        """La fila de títulos completa (con los vacíos), para el Excel para corregir."""
        ancho = max([c.indice + 1 for c in self.columnas] + [len(f) for _, f in self.filas[:1]], default=0)
        porcion = {c.indice: c.titulo for c in self.columnas}
        return [porcion.get(i, "") for i in range(ancho)]

    def mapa(self) -> dict:
        """clave → índice (o lista de índices para las que admiten varias)."""
        mejor: dict = {}
        multiples: dict = {}
        for c in self.columnas:
            if not c.clave:
                continue
            if c.clave in MULTIPLES:
                multiples.setdefault(c.clave, []).append(c.indice)
            else:
                _, _, prioridad = reconocer(c.titulo)
                if c.clave not in mejor or prioridad < mejor[c.clave][1]:
                    mejor[c.clave] = (c.indice, prioridad)
        return {**{k: v[0] for k, v in mejor.items()}, **multiples}


def leer_hojas(libro, campos_existentes: list[CampoPersonalizado]) -> list[Hoja]:
    """Cada hoja con su fila de títulos (la que más columnas reconoce entre las 10 primeras)."""
    por_etiqueta = {normalizar(c.etiqueta): c for c in campos_existentes}
    hojas = []
    for ws in libro.worksheets:
        filas = list(ws.iter_rows(values_only=True))
        mejor, puntaje = 0, -1
        for i, fila in enumerate(filas[:10]):
            p = sum(1 for v in fila if v is not None and reconocer(v)[0])
            if p > puntaje:
                mejor, puntaje = i, p
        titulos = filas[mejor] if filas else ()
        columnas = []
        for i, titulo in enumerate(titulos):
            if titulo in (None, "") or normalizar(titulo) == normalizar(TITULO_ERROR):
                continue
            clave, rol, _ = reconocer(titulo)
            columnas.append(Columna(i, str(titulo).strip(), clave,
                                    None if clave else por_etiqueta.get(normalizar(titulo)), rol))
        datos = [(mejor + 2 + n, f) for n, f in enumerate(filas[mejor + 1:])
                 if f and any(v not in (None, "") and str(v).strip() for v in f)]
        hojas.append(Hoja(ws.title, mejor + 1, columnas, datos))
    return hojas


def analizar(db: Session, contenido: bytes) -> list[dict]:
    """Vista previa: hojas, filas y qué se reconoció de cada columna."""
    campos = db.query(CampoPersonalizado).filter(CampoPersonalizado.entidad == "cobranza",
                                                 CampoPersonalizado.activo.is_(True)).all()
    resultado = []
    for h in leer_hojas(abrir_libro(contenido), campos):
        columnas = []
        for c in h.columnas:
            llenas = sum(1 for _, f in h.filas if c.indice < len(f) and f[c.indice] not in (None, ""))
            columnas.append({
                "titulo": c.titulo, "clave": c.clave, "rol": c.rol,
                "campo": c.campo.etiqueta if c.campo else None, "llenas": llenas,
            })
        resultado.append({"nombre": h.nombre, "fila_titulos": h.fila_titulos, "filas": len(h.filas),
                          "sirve": h.sirve, "columnas": columnas})
    return resultado


# ------------------------------------------------------------ estado

def estado_desde_texto(valor) -> tuple[str, Optional[str]]:
    """'Deuda saldada' → ('pagada', 'pagada'); 'Eliminada de cartera…' → ('eliminada', …); lo demás, abierta."""
    t = normalizar(valor)
    if "eliminad" in t:
        return "eliminada", "eliminada_cartera"
    if "saldad" in t or t in ("pagada", "pagado", "pago total"):
        return "pagada", "pagada"
    if "fallecid" in t:
        return "archivada", "fallecido"
    if "castig" in t:
        return "castigo", "otro"
    if "suspendid" in t:
        return "archivada", "suspendida_cliente"
    if "devuelt" in t:
        return "archivada", "devuelta_cliente"
    return "activa", None


# ------------------------------------------------------------ resultado

@dataclass
class Resultado:
    filas: int = 0
    creadas: int = 0
    actualizadas: int = 0
    ya_existian: int = 0
    deudores_nuevos: int = 0
    contactos_agregados: int = 0
    gestiones_creadas: int = 0
    campos_creados: list = field(default_factory=list)
    filiales_creadas: list = field(default_factory=list)
    errores: list = field(default_factory=list)
    avisos: Counter = field(default_factory=Counter)
    # hoja → {"titulos": [...], "filas": [{fila, valores, marcar, agregar, error}]}
    correccion: dict = field(default_factory=dict)
    _en_correccion: int = 0

    def error(self, hoja: str, fila: int, mensaje: str):
        if len(self.errores) < MAX_ERRORES:
            self.errores.append({"hoja": hoja, "fila": fila, "error": mensaje[:250]})

    def para_corregir(self, hoja: str, titulos: list, m: dict, numero_fila: int, valores: tuple,
                      mensaje: str, error: Optional[Exception] = None):
        """Guarda la fila tal como venía, con las casillas a completar, para el Excel para corregir."""
        if self._en_correccion >= MAX_CORRECCION:
            return
        self._en_correccion += 1
        marcar, agregar = [], []
        for campo in getattr(error, "campos", ()):
            opcional = campo.startswith("?")
            clave = campo.lstrip("?")
            indice = m.get(clave)
            if isinstance(indice, list):
                indice = indice[0] if indice else None
            if isinstance(indice, int):
                marcar.append(indice)
            elif not opcional:
                agregar.append(TITULO_CLAVE.get(clave, clave))
        for indice, titulo in getattr(error, "extras", ()):
            if indice is None:
                agregar.append(titulo)
            else:
                marcar.append(indice)
        datos = self.correccion.setdefault(hoja, {"titulos": [_a_json(x) for x in titulos], "filas": []})
        datos["filas"].append({"fila": numero_fila, "valores": [_a_json(x) for x in valores],
                               "marcar": marcar, "agregar": agregar, "error": mensaje[:250]})

    def dict(self) -> dict:
        return {
            "filas_procesadas": self.filas, "cobranzas_creadas": self.creadas,
            "cobranzas_actualizadas": self.actualizadas, "ya_existian": self.ya_existian,
            "deudores_nuevos": self.deudores_nuevos, "contactos_agregados": self.contactos_agregados,
            "gestiones_creadas": self.gestiones_creadas,
            "campos_creados": self.campos_creados, "filiales_creadas": self.filiales_creadas,
            "errores": self.errores, "total_errores": self._total_errores,
            "avisos": [f"{n} × {texto_aviso}" for texto_aviso, n in self.avisos.most_common()],
            **({"correccion": self.correccion} if self.correccion else {}),
        }

    _total_errores: int = 0


Avance = Callable[..., None]  # avance(hechas, total=None)


# ------------------------------------------------------------ cobranzas

@dataclass
class OpcionesCarga:
    cliente_id: Optional[UUID] = None
    hojas: Optional[list[str]] = None          # None = todas las que sirven
    actualizar: bool = False
    crear_filiales: bool = True
    columnas_extra: list[str] = field(default_factory=list)  # títulos a guardar como campos adicionales
    archivo: str = ""


def _slug(texto_: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", normalizar(texto_)).strip("_")[:40] or "campo"


def _tipo_campo(titulo: str, valores: list) -> str:
    """Tipo de un campo nuevo según sus valores (conservador: ante la duda, texto)."""
    valores = [v for v in valores if v not in (None, "")]
    if not valores:
        return "texto"
    if sum(isinstance(v, (datetime, date)) for v in valores) >= 0.95 * len(valores):
        return "fecha"
    if sum(isinstance(v, (int, float)) for v in valores) >= 0.95 * len(valores):
        dinero = re.search(r"monto|capital|honorario|interes|gasto|total|deuda|saldo|descuento", normalizar(titulo))
        return "monto" if dinero else "numero"
    return "texto"


def preparar_hojas(db: Session, contenido: bytes, op: "OpcionesCarga") -> list[Hoja]:
    """Las hojas a cargar, ya revisadas (ValueError con el problema si no se puede)."""
    campos = db.query(CampoPersonalizado).filter(CampoPersonalizado.entidad == "cobranza",
                                                 CampoPersonalizado.activo.is_(True)).all()
    try:
        libro = abrir_libro(contenido)
    except Exception:
        raise ValueError("No se pudo leer el archivo. ¿Es un Excel .xlsx válido?")
    hojas = [h for h in leer_hojas(libro, campos)
             if (op.hojas is None and h.sirve) or (op.hojas is not None and h.nombre in op.hojas)]
    if not hojas:
        raise ValueError("No hay hojas para cargar: el archivo necesita al menos las columnas RUT y nombre del deudor.")
    for h in hojas:
        faltan = [n for n, c in (("RUT deudor", "rut"), ("Nombre deudor", "nombre"), ("Monto", "monto"))
                  if not h.tiene(c)]
        if faltan:
            raise ValueError(f"A la hoja «{h.nombre}» le faltan columnas: {', '.join(faltan)}.")
        if "cliente" not in h.claves and op.cliente_id is None:
            raise ValueError(f"La hoja «{h.nombre}» no tiene columna Cliente: elige el cliente de la carga.")
    return hojas


def cargar_cobranzas(db: Session, usuario: Usuario, contenido: bytes, op: OpcionesCarga,
                     avance: Avance = lambda n, total=None: None) -> dict:
    res = Resultado()
    hojas = preparar_hojas(db, contenido, op)

    # ---- campos adicionales nuevos (columnas elegidas para guardar)
    elegidas = {normalizar(t) for t in op.columnas_extra}
    nuevos: dict[str, CampoPersonalizado] = {}
    claves_usadas = {c.clave for c in db.query(CampoPersonalizado.clave)
                     .filter(CampoPersonalizado.entidad == "cobranza").all()}
    for h in hojas:
        for c in h.columnas:
            n = normalizar(c.titulo)
            if c.clave or c.campo or n not in elegidas:
                continue
            if n not in nuevos:
                valores = [f[c.indice] for _, f in h.filas if c.indice < len(f)]
                clave = _slug(c.titulo)
                while clave in claves_usadas:
                    clave = f"{clave[:36]}_{len(claves_usadas) % 1000}"
                claves_usadas.add(clave)
                campo = CampoPersonalizado(entidad="cobranza", clave=clave, etiqueta=c.titulo[:100],
                                           tipo=_tipo_campo(c.titulo, valores), cliente_id=op.cliente_id,
                                           orden=100 + len(nuevos))
                db.add(campo)
                nuevos[n] = campo
                res.campos_creados.append(c.titulo)
            c.campo = nuevos[n]
    db.flush()

    # ---- catálogos en memoria (valores planos)
    clientes = [(c.id, {(c.nombre_fantasia or "").lower(), c.razon_social.lower(), c.rut.lower()})
                for c in db.query(Cliente).filter(Cliente.activo.is_(True)).all()]

    def buscar_cliente(nombre: str):
        n = nombre.lower()
        for cid, nombres in clientes:
            if n in nombres:
                return cid
        try:
            rut = normalizar_rut(nombre).lower()
        except ValueError:
            return None
        return next((cid for cid, nombres in clientes if rut in nombres), None)

    filiales = {(f.cliente_id, normalizar(f.nombre)): f.id for f in db.query(Filial).all()}
    usuarios = {}
    for u in db.query(Usuario).filter(Usuario.activo.is_(True)).all():
        usuarios[normalizar(u.nombre)] = u.id
        usuarios[u.email.lower()] = u.id

    # RUT de todo el archivo → deudores y terceros existentes (una consulta por lote de mil).
    ruts, ruts_terceros, ids = set(), set(), set()
    for h in hojas:
        m = h.mapa()
        for _, f in h.filas:
            for clave, destino in (("rut", ruts), ("t_rut", ruts_terceros)):
                if clave in m and m[clave] < len(f):
                    try:
                        destino.add(normalizar_rut(f[m[clave]]))
                    except ValueError:
                        pass
            if "id_externo" in m and m["id_externo"] < len(f) and texto(f[m["id_externo"]]):
                ids.add(texto(f[m["id_externo"]]))
            # Sin RUT de deudor se usa el del paciente: también hay que buscarlo como deudor.
            sin_rut = "rut" not in m or m["rut"] >= len(f) or not texto(f[m["rut"]])
            if sin_rut and h.con_paciente and "t_rut" in m and m["t_rut"] < len(f):
                try:
                    ruts.add(normalizar_rut(f[m["t_rut"]]))
                except ValueError:
                    pass
    deudores: dict[str, Deudor] = {}
    for parte in _partes(sorted(ruts)):
        for d in db.query(Deudor).options(selectinload(Deudor.contactos)).filter(Deudor.rut.in_(parte)):
            deudores[d.rut] = d
    terceros: dict[str, Tercero] = {}
    for parte in _partes(sorted(ruts_terceros)):
        for t in db.query(Tercero).options(selectinload(Tercero.contactos)).filter(Tercero.rut.in_(parte)):
            terceros[t.rut] = t
    existentes: dict[tuple, Cobranza] = {}
    for parte in _partes(sorted(ids)):
        for c in db.query(Cobranza).filter(Cobranza.id_externo.in_(parte)):
            existentes[(c.cliente_id, c.filial_id, c.id_externo)] = c

    obligatorios: dict = {}  # cliente → campos obligatorios (una consulta por cliente)
    vistos: set = set()      # deudores ya tocados en este archivo: manda su primera fila
    total = sum(len(h.filas) for h in hojas)
    avance(0, total)
    hechas = 0
    for h in hojas:
        m = h.mapa()
        titulos = h.titulos()
        extras = [c for c in h.columnas if c.campo is not None]
        for numero_fila, fila in h.filas:
            res.filas += 1
            hechas += 1

            def v(clave):
                i = m.get(clave)
                return fila[i] if isinstance(i, int) and i < len(fila) else None

            def varios(clave):
                return [fila[i] for i in m.get(clave, []) if i < len(fila) and fila[i] not in (None, "")]

            punto = db.begin_nested()
            # Si la fila falla se deshace en la base (savepoint) y también aquí:
            # contadores y lo que agregó a los catálogos en memoria (una filial
            # nueva que no quedó no puede seguir usándose en las filas siguientes).
            deshacer: list = []
            contadores = (len(res.filiales_creadas), res.deudores_nuevos, res.contactos_agregados)

            def revertir():
                punto.rollback()
                for catalogo, clave in deshacer:
                    catalogo.pop(clave, None)
                del res.filiales_creadas[contadores[0]:]
                res.deudores_nuevos, res.contactos_agregados = contadores[1], contadores[2]

            try:
                nuevo_deudor = _fila_cobranza(db, usuario, op, res, h, m, v, varios, extras, fila,
                                              buscar_cliente, filiales, usuarios, deudores, terceros, existentes,
                                              obligatorios, vistos, deshacer)
                punto.commit()
                if nuevo_deudor is not None:
                    deudores[nuevo_deudor.rut] = nuevo_deudor
            except (ValueError, ErrorCampo) as e:
                revertir()
                res._total_errores += 1
                res.error(h.nombre, numero_fila, str(e))
                res.para_corregir(h.nombre, titulos, m, numero_fila, fila, str(e), e)
            except Exception as e:  # noqa: BLE001 — una fila mala no frena la carga
                revertir()
                res._total_errores += 1
                mensaje = str(e)
                marcar = None
                if "uq_cobranza_id_externo" in mensaje:
                    mensaje = f"El ID cliente '{texto(v('id_externo'))}' ya existe en esa filial"
                    marcar = ErrorFila(mensaje, "id_externo")
                else:
                    mensaje = "No se pudo guardar la fila (dato inválido o repetido)."
                res.error(h.nombre, numero_fila, mensaje)
                res.para_corregir(h.nombre, titulos, m, numero_fila, fila, mensaje, marcar)
            if hechas % LOTE == 0:
                avance(hechas)
                db.commit()
    avance(total)
    db.commit()
    return res.dict()


def _partes(lista, tamano=1000):
    for i in range(0, len(lista), tamano):
        yield lista[i:i + tamano]


def _rut_o_none(valor) -> Optional[str]:
    try:
        return normalizar_rut(valor)
    except ValueError:
        return None


def _deudor_de_la_fila(h: "Hoja", v, deudores: dict, res: "Resultado") -> tuple[str, str, Optional[str]]:
    """
    RUT y nombre del deudor de una fila, con el paciente como respaldo:
      - sin RUT de deudor: el deudor es el paciente (su RUT y su nombre);
      - sin nombre: el que ya tiene ese RUT en el sistema o, si el RUT es el
        del paciente, el nombre del paciente. Si el RUT es de otra persona no
        se le pone el nombre del paciente (quedaría con un nombre equivocado):
        la fila va al Excel para corregir.
    Devuelve (rut, nombre, nota para las observaciones de la cobranza).
    """
    rut_crudo, nombre = texto(v("rut")), texto(v("nombre"))
    rut_pac, nombre_pac = (texto(v("t_rut")), texto(v("t_nombre"))) if h.con_paciente else ("", "")
    nota = None
    if not rut_crudo:
        if not rut_pac:
            raise ErrorFila("Falta el RUT del deudor" + (" (y el del paciente)" if h.con_paciente else ""), "rut")
        try:
            rut = normalizar_rut(rut_pac)
        except ValueError as e:
            raise ErrorFila(f"Falta el RUT del deudor y el del paciente no sirve: {e}", "rut", "t_rut")
        if nombre and nombre_pac and normalizar(nombre) != normalizar(nombre_pac):
            nota = f"Deudor según la planilla: {nombre} (sin RUT); se tomó al paciente como deudor."
        conocido = deudores.get(rut)
        nombre = nombre_pac or (conocido.nombre if conocido is not None else "")
        if not nombre:
            raise ErrorFila("Falta el RUT del deudor y el nombre del paciente", "rut", "t_nombre")
        res.avisos["sin RUT de deudor: se tomó al paciente como deudor"] += 1
        return rut, nombre, nota
    try:
        rut = normalizar_rut(rut_crudo)
    except ValueError as e:
        raise ErrorFila(str(e), "rut")
    if not nombre:
        conocido = deudores.get(rut)
        if conocido is not None:
            nombre = conocido.nombre
        elif nombre_pac and _rut_o_none(rut_pac) == rut:
            nombre = nombre_pac
            res.avisos["sin nombre de deudor: se usó el del paciente"] += 1
        else:
            raise ErrorFila("Falta el nombre del deudor", "nombre")
    return rut, nombre, nota


def _a_json(valor):
    """Valor de una celda guardable en el resultado (las fechas, marcadas)."""
    if isinstance(valor, datetime):
        return {"fecha": valor.isoformat()}
    if isinstance(valor, date):
        return {"fecha": valor.isoformat()}
    if isinstance(valor, Decimal):
        return float(valor)
    if valor is None or isinstance(valor, (str, int, float, bool)):
        return valor
    return str(valor)


def _de_json(valor):
    if isinstance(valor, dict) and "fecha" in valor:
        f = datetime.fromisoformat(valor["fecha"])
        return f if "T" in valor["fecha"] and f.time() != time(0) else f.date()
    return valor


AMARILLO = PatternFill("solid", fgColor="FFEB3B")
GRIS = PatternFill("solid", fgColor="E4E4E7")
ROJO_CLARO = PatternFill("solid", fgColor="FDE2E1")


def excel_para_corregir(correccion: dict) -> bytes:
    """
    Las filas que no entraron, tal como venían (misma hoja y mismos títulos),
    con las casillas a completar en amarillo y el motivo en la última columna.
    Se completa y se vuelve a subir tal cual: el motivo se ignora.
    """
    wb = Workbook()
    wb.remove(wb.active)
    for hoja, datos in correccion.items():
        ws = wb.create_sheet((hoja or "Hoja")[:31])
        filas = datos["filas"]
        titulos = [_de_json(x) for x in datos["titulos"]]
        ancho = max([len(titulos)] + [len(f["valores"]) for f in filas])
        agregadas: list[str] = []
        for f in filas:
            for titulo in f["agregar"]:
                if titulo not in agregadas:
                    agregadas.append(titulo)
        ws.append([*titulos, *[""] * (ancho - len(titulos)), *agregadas, TITULO_ERROR])
        for i, celda in enumerate(ws[1], start=1):
            celda.font = Font(bold=True)
            celda.fill = AMARILLO if ancho < i <= ancho + len(agregadas) else ROJO_CLARO if i == ancho + len(agregadas) + 1 else GRIS
        for f in filas:
            valores = [_de_json(x) for x in f["valores"]]
            ws.append([*valores, *[None] * (ancho - len(valores)), *[None] * len(agregadas), f["error"]])
            r = ws.max_row
            for celda in ws[r]:
                if isinstance(celda.value, datetime):
                    celda.number_format = "DD-MM-YYYY HH:MM"
                elif isinstance(celda.value, date):
                    celda.number_format = "DD-MM-YYYY"
                elif isinstance(celda.value, int) and abs(celda.value) >= 10**11:
                    celda.number_format = "0"  # teléfonos y N° largos, sin notación científica
            for i in f["marcar"]:
                ws.cell(r, i + 1).fill = AMARILLO
            for titulo in f["agregar"]:
                ws.cell(r, ancho + agregadas.index(titulo) + 1).fill = AMARILLO
            motivo = ws.cell(r, ancho + len(agregadas) + 1)
            motivo.fill = ROJO_CLARO
            motivo.alignment = Alignment(wrap_text=True, vertical="top")
        for i, titulo in enumerate([*titulos, *[""] * (ancho - len(titulos)), *agregadas, TITULO_ERROR], start=1):
            letra = ws.cell(1, i).column_letter
            ws.column_dimensions[letra].width = 60 if titulo == TITULO_ERROR else min(max(len(str(titulo or "")) + 4, 12), 40)
        ws.freeze_panes = "A2"
    salida = BytesIO()
    wb.save(salida)
    return salida.getvalue()


def _fila_cobranza(db, usuario, op, res, h, m, v, varios, extras, fila,
                   buscar_cliente, filiales, usuarios, deudores, terceros, existentes, obligatorios, vistos,
                   deshacer: list):
    """Procesa una fila. Devuelve el deudor si es nuevo (para reutilizarlo en las filas siguientes)."""
    rut, nombre, nota_deudor = _deudor_de_la_fila(h, v, deudores, res)

    cliente_id = op.cliente_id
    if texto(v("cliente")):
        cliente_id = buscar_cliente(texto(v("cliente")))
        if cliente_id is None:
            raise ErrorFila(f"El cliente '{texto(v('cliente'))}' no existe en el sistema", "cliente")

    filial_id = None
    nombre_filial = texto(v("filial"))
    if nombre_filial:
        filial_id = filiales.get((cliente_id, normalizar(nombre_filial)))
        if filial_id is None:
            if not op.crear_filiales:
                raise ErrorFila(f"La filial '{nombre_filial}' no existe para ese cliente", "filial")
            filial = Filial(cliente_id=cliente_id, nombre=nombre_filial.strip().title()[:100])
            db.add(filial)
            db.flush()
            filiales[(cliente_id, normalizar(nombre_filial))] = filial.id
            deshacer.append((filiales, (cliente_id, normalizar(nombre_filial))))
            filial_id = filial.id
            res.filiales_creadas.append(filial.nombre)

    ejecutivo_id = None
    if texto(v("ejecutivo")):
        ejecutivo_id = usuarios.get(normalizar(v("ejecutivo"))) or usuarios.get(texto(v("ejecutivo")).lower())
        if ejecutivo_id is None:
            res.avisos[f"ejecutivo '{texto(v('ejecutivo'))}' no es un usuario: quedó sin asignar"] += 1

    # ---- datos de la cobranza que trae la fila
    datos: dict = {}
    numero_doc_clave = next((k for k in ("numero_documento", "n_pagare", "n_factura", "n_cheque", "n_letra")
                             if texto(v(k))), None)
    if numero_doc_clave:
        datos["numero_documento"] = texto(v(numero_doc_clave))[:50]
    tipo_doc = normalizar(v("tipo_documento")).replace(" ", "") or TIPO_POR_COLUMNA.get(numero_doc_clave or "")
    if tipo_doc:
        if tipo_doc not in TIPOS_DOCUMENTO:
            raise ErrorFila(f"Tipo de documento inválido: '{texto(v('tipo_documento'))}' "
                            f"(usar: {', '.join(sorted(TIPOS_DOCUMENTO))})", "tipo_documento")
        datos["tipo_documento"] = tipo_doc
    for clave in ("fecha_vencimiento_documento", "fecha_origen", "fecha_ingreso", "fecha_traspaso",
                  "fecha_envio_documentos"):
        f = fecha(v(clave))
        if f:
            datos[clave] = f
    if texto(v("comprobante_envio")):
        datos["comprobante_envio"] = texto(v("comprobante_envio"))[:200]
    if si_no(v("autorizacion_firma")) is not None:
        datos["autorizacion_firma"] = si_no(v("autorizacion_firma"))
    if texto(v("estado")):
        datos["etapa_cobranza"] = texto(v("estado"))[:50]
    if ejecutivo_id:
        datos["ejecutivo_id"] = ejecutivo_id
    datos_extra = {}
    for c in extras:
        valor = fila[c.indice] if c.indice < len(fila) else None
        if valor in (None, ""):
            continue
        if c.campo.cliente_id is not None and c.campo.cliente_id != cliente_id:
            continue
        try:
            datos_extra[c.campo.clave] = convertir_valor(c.campo, valor)
        except ErrorCampo:
            res.avisos[f"valor no válido en «{c.campo.etiqueta}» (se omitió)"] += 1

    id_externo = texto(v("id_externo"))[:50] or None
    existente = existentes.get((cliente_id, filial_id, id_externo)) if id_externo else None

    if existente is not None and not op.actualizar:
        res.ya_existian += 1
        return None

    # ---- deudor (el de la cobranza existente, que debe ser el mismo RUT)
    if existente is not None:
        if existente.deudor.rut != rut:
            raise ErrorFila(f"El RUT {rut} no coincide con el de la cobranza ID '{id_externo}' "
                            f"({existente.deudor.rut}): no se actualizó", "rut", "id_externo")
        deudores.setdefault(rut, existente.deudor)
    deudor = deudores.get(rut)
    nuevo = deudor is None
    # Un deudor con varias cuentas aparece en varias filas, a veces con datos
    # distintos: solo la primera fila del archivo puede reemplazar sus datos.
    primera_vez = rut not in vistos
    vistos.add(rut)
    cambios_deudor: list[str] = []
    if nuevo:
        deudor = Deudor(rut=rut, nombre=nombre[:200])
        deudor.contactos = []
        db.add(deudor)
        res.deudores_nuevos += 1
    for campo in ("direccion", "comuna", "ciudad", "region"):
        valor = texto(v(campo))
        if valor and (nuevo or not getattr(deudor, campo)
                      or (op.actualizar and primera_vez and getattr(deudor, campo) != valor)):
            if not nuevo and getattr(deudor, campo) != valor:
                cambios_deudor.append(f"{campo.capitalize()}: {getattr(deudor, campo) or '—'} → {valor}")
            setattr(deudor, campo, valor[:100] if campo != "direccion" else valor)
    dicom = si_no(v("dicom"))
    if dicom is not None and deudor.en_boletin_comercial != dicom and (nuevo or primera_vez):
        if not nuevo:
            cambios_deudor.append(f"DICOM: {'sí' if dicom else 'no'}")
        deudor.en_boletin_comercial = dicom

    # Contactos: los del deudor y, si el tercero es la misma persona, también los suyos.
    rut_tercero = None
    if texto(v("t_rut")):
        try:
            rut_tercero = normalizar_rut(v("t_rut"))
        except ValueError:
            res.avisos["RUT de tercero inválido (se omitió el tercero)"] += 1
    mismo = rut_tercero == rut
    telefonos = varios("telefono") + (varios("t_telefono") if mismo else [])
    emails = varios("email") + (varios("t_email") if mismo else [])
    agregados = _agregar_contactos(deudor.contactos, telefonos, emails,
                                   lambda tipo, valor: ContactoDeudor(tipo=tipo, valor=valor))
    res.contactos_agregados += len(agregados) if not nuevo else 0
    if agregados and not nuevo:
        cambios_deudor.append("Contactos agregados: " + ", ".join(agregados))
    db.flush()

    # ---- cobranza nueva o actualizada
    if existente is None:
        try:
            valor_monto = monto(v("monto"))
        except ValueError:
            valor_monto = None
        if valor_monto is None or valor_monto <= 0:
            raise ErrorFila("Falta el saldo capital" if texto(v("monto")) == ""
                            else f"Saldo capital inválido: {v('monto')!r}", "monto")
        estado, motivo = estado_desde_texto(v("estado")) if texto(v("estado")) else ("activa", None)
        if cliente_id not in obligatorios:
            obligatorios[cliente_id] = [(c.clave, c.etiqueta) for c in campos_aplicables(db, "cobranza", cliente_id)
                                        if c.obligatorio]
        faltan = [(clave, etiqueta) for clave, etiqueta in obligatorios[cliente_id] if clave not in datos_extra]
        if faltan:
            raise ErrorFila("Falta: " + ", ".join(etiqueta for _, etiqueta in faltan), extras=tuple(
                (next((c.indice for c in extras if c.campo.clave == clave), None), etiqueta)
                for clave, etiqueta in faltan))
        cobranza = Cobranza(
            cliente_id=cliente_id, filial_id=filial_id, deudor_id=deudor.id, id_externo=id_externo,
            monto_original=valor_monto, monto_actual=Decimal(0) if estado == "pagada" else valor_monto,
            tipo_documento=datos.pop("tipo_documento", "pagare"),
            observaciones="\n".join(x for x in (texto(v("observaciones")), nota_deudor) if x) or None,
            datos_extra=datos_extra,
            estado=estado, motivo_cierre=motivo,
            fecha_cierre=hoy_chile() if estado in ciclo.ESTADOS_TERMINALES else None,
            **datos,
        )
        db.add(cobranza)
        db.flush()
        if id_externo:
            existentes[(cliente_id, filial_id, id_externo)] = cobranza
            deshacer.append((existentes, (cliente_id, filial_id, id_externo)))
        res.creadas += 1
    else:
        cobranza = existente
        cambios = {k: val for k, val in datos.items() if getattr(cobranza, k) != val}
        if datos_extra:
            fusion = {**(cobranza.datos_extra or {}), **datos_extra}
            if fusion != (cobranza.datos_extra or {}):
                cambios["datos_extra"] = fusion
        try:
            nuevo_monto = monto(v("monto"))
        except ValueError:
            raise ErrorFila(f"Saldo capital inválido: {v('monto')!r}", "monto")
        if nuevo_monto and nuevo_monto != cobranza.monto_original:
            tiene_pagos = db.query(Pago.id).filter(Pago.cobranza_id == cobranza.id, PAGO_VIGENTE).first()
            if tiene_pagos:
                res.avisos["monto distinto en una cobranza con pagos: no se cambió (revisar a mano)"] += 1
            else:
                cambios["monto_original"] = nuevo_monto
                cambios["monto_actual"] = nuevo_monto
        antes = {k: getattr(cobranza, k) for k in cambios}
        for k, val in cambios.items():
            setattr(cobranza, k, val)
        # Estado: lo único que se aplica solo es lo que indica el cliente al
        # sacar un caso (eliminada de cartera); lo demás se avisa.
        if texto(v("estado")):
            estado, motivo = estado_desde_texto(v("estado"))
            if estado == "eliminada" and cobranza.estado in ABIERTAS:
                cobranza.estado, cobranza.motivo_cierre, cobranza.fecha_cierre = estado, motivo, hoy_chile()
                registrar_cambio(db, [cobranza.id], usuario.id, "eliminada_cartera",
                                 f"ELIMINADA DE CARTERA por indicación del cliente (carga {op.archivo}).")
            elif estado != "activa" and estado != cobranza.estado:
                res.avisos[f"«{texto(v('estado'))}» en la planilla: el estado no se cambió solo"] += 1
        detalle = describir_cambios(antes, cambios, {"monto_original": "Monto", "monto_actual": "Saldo",
                                                     "etapa_cobranza": "Etapa según el cliente"})
        detalle = "; ".join(x for x in [detalle, *cambios_deudor] if x)
        if detalle:
            registrar_cambio(db, [cobranza.id], usuario.id, "cambio_datos",
                             f"DATOS ACTUALIZADOS POR CARGA MASIVA ({op.archivo}): {detalle}.")
            res.actualizadas += 1
        else:
            res.ya_existian += 1

    # ---- tercero (paciente, aval…)
    if rut_tercero and not mismo:
        rol = next((c.rol for c in h.columnas if c.clave and c.clave.startswith("t_") and c.rol), "tercero")
        tercero = terceros.get(rut_tercero)
        if tercero is None:
            tercero = Tercero(rut=rut_tercero, nombre=(texto(v("t_nombre")) or "Sin nombre")[:200])
            tercero.contactos = []
            db.add(tercero)
            terceros[rut_tercero] = tercero
            deshacer.append((terceros, rut_tercero))
        for campo in ("direccion", "comuna", "ciudad", "region"):
            if texto(v(f"t_{campo}")) and not getattr(tercero, campo):
                setattr(tercero, campo, texto(v(f"t_{campo}")))
        _agregar_contactos(tercero.contactos, varios("t_telefono"), varios("t_email"),
                           lambda tipo, valor: ContactoTercero(tipo=tipo, valor=valor))
        db.flush()
        if not db.get(CobranzaTercero, (cobranza.id, tercero.id, rol)):
            db.add(CobranzaTercero(cobranza_id=cobranza.id, tercero_id=tercero.id, rol=rol))
    db.flush()
    return deudor if nuevo else None


def _agregar_contactos(actuales: list, telefonos: list, emails: list, crear) -> list[str]:
    """Agrega los teléfonos y correos que la persona no tenga. Devuelve lo agregado."""
    vistos = set()
    for c in actuales:
        if c.tipo == "email":
            vistos.add(c.valor.lower())
        else:
            t = telefono(c.valor)
            vistos.add(t[2] if t else c.valor)
    agregados = []
    for crudo in telefonos:
        t = telefono(crudo)
        if t and t[2] not in vistos:
            vistos.add(t[2])
            actuales.append(crear(t[0], t[1]))
            agregados.append(t[1])
    for crudo in emails:
        for correo in correos(crudo):
            if correo not in vistos:
                vistos.add(correo)
                actuales.append(crear("email", correo))
                agregados.append(correo)
    return agregados


# ------------------------------------------------------------ gestiones

COLUMNAS_GESTION: dict[str, list[str]] = {
    "numero": ["n cobranza", "numero cobranza", "nro cobranza", "numero de cobranza", "n de cobranza"],
    "id_externo": ["id cliente", "id", "id cuenta", "n cuenta", "numero cuenta", "cuenta"],
    "rut": ["rut deudor", "rut", "rut del deudor"],
    "cliente": ["cliente", "mandante"],
    "filial": ["filial", "sucursal"],
    "fecha": ["fecha", "fecha gestion", "fecha de gestion"],
    "tipo": ["tipo", "tipo gestion", "tipo de gestion", "accion", "canal"],
    "descripcion": ["gestion", "descripcion", "detalle", "comentario", "observacion", "texto"],
    "persona": ["persona", "usuario", "ejecutivo", "ejecutiva", "gestor", "realizada por", "responsable"],
    "proximo": ["proximo contacto", "fecha proximo contacto", "volver a contactar", "volver a llamar"],
}
# Palabras comunes → código del tipo de gestión de sistema.
SINONIMOS_TIPO = {
    "llamada": "llamada", "llamado": "llamada", "telefono": "llamada", "llamada telefonica": "llamada",
    "whatsapp": "whatsapp", "wsp": "whatsapp", "wsp mensaje": "whatsapp", "mensaje whatsapp": "whatsapp",
    "correo": "email", "email": "email", "mail": "email", "correo electronico": "email", "email enviado": "email",
    "sms": "sms", "mensaje de texto": "sms", "visita": "visita", "terreno": "visita",
    "carta": "carta", "no contesta": "no_contesta", "sin respuesta": "no_contesta",
    "promesa": "promesa_pago", "promesa de pago": "promesa_pago", "negativa": "negativa_pago",
    "nota": "nota", "nota interna": "nota",
}


def cargar_gestiones(db: Session, usuario: Usuario, contenido: bytes, cliente_id: Optional[UUID],
                     archivo: str = "", avance: Avance = lambda n, total=None: None) -> dict:
    res = Resultado()
    try:
        ws = abrir_libro(contenido).active
    except Exception:
        raise ValueError("No se pudo leer el archivo. ¿Es un Excel .xlsx válido?")
    filas = list(ws.iter_rows(values_only=True))
    # Fila de títulos: la que más columnas reconoce entre las 10 primeras.
    reconocidas = [sum(1 for v in f if any(normalizar(v) in t for t in COLUMNAS_GESTION.values()))
                   for f in filas[:10]]
    if not reconocidas or max(reconocidas) < 2:
        raise ValueError("No se reconocen las columnas: usa la plantilla de gestiones.")
    i_titulos = reconocidas.index(max(reconocidas))
    titulos = ["" if normalizar(x) == normalizar(TITULO_ERROR) else x for x in filas[i_titulos]]
    m: dict = {}
    for i, titulo in enumerate(titulos):
        n = normalizar(titulo)
        for clave, titulos in COLUMNAS_GESTION.items():
            if n in titulos and clave not in m:
                m[clave] = i
    if not ({"numero", "id_externo", "rut"} & set(m)):
        raise ValueError("Falta una columna para identificar la cobranza: N° cobranza, ID cliente o RUT deudor.")
    if "descripcion" not in m and "tipo" not in m:
        raise ValueError("Falta la columna Gestión (o al menos Tipo).")

    tipos = {}
    for t in db.query(TipoGestion).all():
        tipos[normalizar(t.nombre)] = t.id
        if t.codigo:
            tipos[normalizar(t.codigo)] = t.id
    por_codigo = {}
    for codigo in set(SINONIMOS_TIPO.values()):
        t = tipo_de_sistema(db, codigo)
        if t:
            por_codigo[codigo] = t.id
    usuarios = {}
    for u in db.query(Usuario).filter(Usuario.activo.is_(True)).all():
        usuarios[normalizar(u.nombre)] = u.id
        usuarios[u.email.lower()] = u.id
    clientes = [(c.id, {(c.nombre_fantasia or "").lower(), c.razon_social.lower(), c.rut.lower()})
                for c in db.query(Cliente).all()]
    filiales = {(f.cliente_id, normalizar(f.nombre)): f.id for f in db.query(Filial).all()}

    datos = [(i_titulos + 2 + n, f) for n, f in enumerate(filas[i_titulos + 1:])
             if f and any(v not in (None, "") and str(v).strip() for v in f)]
    avance(0, len(datos))
    for hechas, (numero_fila, fila) in enumerate(datos, start=1):
        res.filas += 1

        def v(clave):
            i = m.get(clave)
            return fila[i] if i is not None and i < len(fila) else None

        punto = db.begin_nested()
        try:
            cid = cliente_id
            if texto(v("cliente")):
                n = texto(v("cliente")).lower()
                cid = next((c for c, nombres in clientes if n in nombres), None)
                if cid is None:
                    raise ErrorFila(f"El cliente '{texto(v('cliente'))}' no existe", "cliente")
            cobranza = _buscar_cobranza(db, v, cid, filiales)

            tipo_id = None
            if texto(v("tipo")):
                n = normalizar(v("tipo"))
                tipo_id = tipos.get(n) or por_codigo.get(SINONIMOS_TIPO.get(n, ""))
                if tipo_id is None:
                    raise ErrorFila(f"Tipo de gestión desconocido: '{texto(v('tipo'))}'", "tipo")
            descripcion = texto(v("descripcion")) or texto(v("tipo"))
            if not descripcion:
                raise ErrorFila("Falta el texto de la gestión", "descripcion")
            autor = usuario.id
            if texto(v("persona")):
                autor = usuarios.get(normalizar(v("persona"))) or usuarios.get(texto(v("persona")).lower())
                if autor is None:
                    raise ErrorFila(f"La persona '{texto(v('persona'))}' no es un usuario del sistema", "persona")
            gestion = Gestion(cobranza_id=cobranza.id, usuario_id=autor, tipo_id=tipo_id,
                              descripcion=descripcion, es_masivo=True,
                              fecha_proximo_contacto=fecha(v("proximo")))
            cuando = v("fecha")
            if isinstance(cuando, datetime):
                gestion.fecha_gestion = cuando
            elif fecha(cuando):
                f = fecha(cuando)
                gestion.fecha_gestion = datetime.combine(f, time(12))
            db.add(gestion)
            db.flush()
            punto.commit()
            res.gestiones_creadas += 1
        except ValueError as e:
            punto.rollback()
            res._total_errores += 1
            res.error(ws.title, numero_fila, str(e))
            res.para_corregir(ws.title, titulos, m, numero_fila, fila, str(e), e)
        except Exception:  # noqa: BLE001
            punto.rollback()
            res._total_errores += 1
            res.error(ws.title, numero_fila, "No se pudo guardar la fila.")
            res.para_corregir(ws.title, titulos, m, numero_fila, fila, "No se pudo guardar la fila.")
        if hechas % LOTE == 0:
            avance(hechas)
            db.commit()
    avance(len(datos))
    db.commit()
    return res.dict()


def _buscar_cobranza(db: Session, v, cliente_id, filiales) -> Cobranza:
    """N° de cobranza → ID cliente (y filial) → RUT del deudor (si tiene una sola abierta)."""
    numero = texto(v("numero"))
    if numero:
        try:
            cob = db.query(Cobranza).filter(Cobranza.numero == int(numero)).first()
        except ValueError:
            raise ErrorFila(f"N° de cobranza inválido: '{numero}'", "numero")
        if cob is None:
            raise ErrorFila(f"No existe la cobranza N° {numero}", "numero")
        return cob
    q = db.query(Cobranza)
    if cliente_id is not None:
        q = q.filter(Cobranza.cliente_id == cliente_id)
    id_externo = texto(v("id_externo"))
    if id_externo:
        q = q.filter(Cobranza.id_externo == id_externo)
        if texto(v("filial")):
            filial_id = filiales.get((cliente_id, normalizar(v("filial"))))
            if filial_id is None:
                raise ErrorFila(f"La filial '{texto(v('filial'))}' no existe para ese cliente", "filial")
            q = q.filter(Cobranza.filial_id == filial_id)
        encontradas = q.limit(3).all()
        if not encontradas:
            raise ErrorFila(f"No existe una cobranza con ID cliente '{id_externo}'", "id_externo")
        if len(encontradas) > 1:
            raise ErrorFila(f"El ID cliente '{id_externo}' está en varias filiales o clientes: indica la filial",
                            "filial")
        return encontradas[0]
    rut_crudo = texto(v("rut"))
    if not rut_crudo:
        raise ErrorFila("La fila no trae N° de cobranza, ID cliente ni RUT", "?numero", "?id_externo", "?rut")
    try:
        rut = normalizar_rut(rut_crudo)
    except ValueError as e:
        raise ErrorFila(str(e), "rut")
    abiertas = (q.join(Deudor, Deudor.id == Cobranza.deudor_id)
                .filter(Deudor.rut == rut, Cobranza.estado.in_(ABIERTAS)).limit(3).all())
    if not abiertas:
        raise ErrorFila(f"El RUT {rut} no tiene cobranzas abiertas", "rut")
    if len(abiertas) > 1:
        raise ErrorFila(f"El RUT {rut} tiene varias cobranzas abiertas: indica el ID cliente o el N°",
                        "?numero", "id_externo")
    return abiertas[0]

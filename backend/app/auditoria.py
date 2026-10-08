"""
Auditoría automática con eventos de SQLAlchemy.

Cómo funciona:
  1. get_current_user (security.py) guarda en session.info quién es el
     usuario de la petición actual y desde qué IP llegó. Se usa session.info
     (y NO un ContextVar) porque FastAPI ejecuta las dependencias sync en
     threads distintos al endpoint y el ContextVar se perdería; la sesión de
     DB en cambio es el mismo objeto compartido durante toda la petición.
  2. El listener 'after_flush' se dispara en CADA flush de CUALQUIER sesión:
     revisa qué objetos se insertaron/modificaron/borraron y escribe las
     filas correspondientes en audit_log, en la MISMA transacción (si el
     cambio se revierte, la auditoría también).

Ventaja de este enfoque: ningún router necesita acordarse de auditar.
Es imposible "olvidarse" — todo cambio en tablas auditadas queda registrado.

Este módulo se importa desde main.py para registrar el listener al arrancar.
"""

from uuid import UUID
from datetime import date, datetime, time
from decimal import Decimal
from typing import Optional

from sqlalchemy import event, insert, inspect as sa_inspect
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.organizacion import Organizacion
from app.tenancy import CLAVE_ORGANIZACION


# Clave bajo la que security.py guarda el contexto en session.info.
CLAVE_CONTEXTO = "auditoria"

# Tablas que NO se auditan: la propia auditoría (evita recursión), las
# bitácoras de seguridad (ya son un registro en sí) y los catálogos de
# sistema que solo cambian en mantenciones.
TABLAS_EXCLUIDAS = {
    "audit_log", "roles", "eventos_acceso", "sesiones", "tokens_un_uso",
}

# Tablas inmutables (la base impide editarlas o borrarlas): el registro
# mismo ya guarda quién lo hizo y cuándo, así que su ALTA no se copia al
# log. Sin esto, la auditoría pesaba casi el doble que las gestiones (medido:
# 825 bytes de log por cada gestión de 480 bytes).
TABLAS_INMUTABLES = {"gestiones", "pagos"}

# Campos cuyo VALOR nunca debe quedar en el log.
CAMPOS_ENMASCARADOS = {
    "password_hash", "mfa_secreto_cifrado", "mfa_codigos_recuperacion",
    "refresh_hash", "refresh_anterior_hash", "token_hash", "logo",
}

# Campos que cambian solos con el uso (login, contadores): un UPDATE que
# solo toca estos no se registra, para no llenar el log de ruido.
CAMPOS_RUIDO = {
    "ultimo_acceso", "intentos_fallidos", "bloqueado_hasta", "mfa_ultimo_paso",
    "updated_at", "numero_cobranza_siguiente", "accesos", "ultimo_acceso_at",
}


def _valor(v):
    """Convierte un valor a algo serializable en JSON (para JSONB)."""
    if isinstance(v, (UUID,)):
        return str(v)
    if isinstance(v, (datetime, date, time)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return f"<{len(v)} bytes>"
    return v


def _serializar(obj) -> dict:
    """
    Foto completa de un objeto (solo columnas ya cargadas: no dispara
    queries extra, que dentro de after_flush están prohibidas).
    """
    insp = sa_inspect(obj)
    datos = {}
    for col in obj.__table__.columns:
        if col.name in insp.unloaded:
            continue  # server_default aún no traído de la DB (ej. created_at)
        valor = getattr(obj, col.name)
        datos[col.name] = "***" if col.name in CAMPOS_ENMASCARADOS else _valor(valor)
    return datos


def _cambios(obj) -> tuple:
    """Para un UPDATE: devuelve ({campo: valor_viejo}, {campo: valor_nuevo})."""
    insp = sa_inspect(obj)
    nombres_columnas = {c.name for c in obj.__table__.columns}
    antes, despues = {}, {}
    for attr in insp.attrs:
        if attr.key not in nombres_columnas:
            continue  # saltar relationships
        hist = attr.load_history()
        if not hist.has_changes():
            continue
        viejo = _valor(hist.deleted[0]) if hist.deleted else None
        nuevo = _valor(hist.added[0]) if hist.added else None
        if attr.key in CAMPOS_ENMASCARADOS:
            viejo, nuevo = "***", "***"
        antes[attr.key] = viejo
        despues[attr.key] = nuevo
    return antes, despues


def _organizacion(obj, session):
    if isinstance(obj, Organizacion):
        return obj.id
    return getattr(obj, "organizacion_id", None) or session.info.get(CLAVE_ORGANIZACION)


def _entrada(obj, accion: str, ctx: Optional[dict],
             antes: Optional[dict], despues: Optional[dict], session) -> dict:
    return {
        "organizacion_id": _organizacion(obj, session),
        "usuario_id": ctx.get("usuario_id") if ctx else None,
        "accion": accion,
        "tabla": obj.__table__.name,
        "registro_id": str(sa_inspect(obj).identity[0]) if sa_inspect(obj).identity else str(getattr(obj, "id", "?")),
        "datos_anteriores": antes,
        "datos_nuevos": despues,
        "ip_origen": ctx.get("ip") if ctx else None,
    }


@event.listens_for(Session, "after_flush")
def registrar_auditoria(session, flush_context):
    """Se ejecuta después de cada flush: registra los cambios en audit_log."""
    ctx = session.info.get(CLAVE_CONTEXTO)
    entradas = []

    for obj in session.new:
        if obj.__table__.name in TABLAS_EXCLUIDAS or obj.__table__.name in TABLAS_INMUTABLES:
            continue
        entradas.append(_entrada(obj, "INSERT", ctx, None, _serializar(obj), session))

    for obj in session.dirty:
        if obj.__table__.name in TABLAS_EXCLUIDAS:
            continue
        if not session.is_modified(obj, include_collections=False):
            continue
        antes, despues = _cambios(obj)
        if set(despues) - CAMPOS_RUIDO:
            entradas.append(_entrada(obj, "UPDATE", ctx, antes, despues, session))

    for obj in session.deleted:
        if obj.__table__.name in TABLAS_EXCLUIDAS:
            continue
        entradas.append(_entrada(obj, "DELETE", ctx, _serializar(obj), None, session))

    if entradas:
        # Insert directo con Core (no ORM): no re-dispara este listener.
        session.execute(insert(AuditLog.__table__), entradas)

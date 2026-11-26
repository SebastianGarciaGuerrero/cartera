"""
Trabajos en segundo plano: una carga masiva grande no deja a la persona
esperando con la pantalla congelada (ni corta la conexión). Se crea el
trabajo, se responde de inmediato con su id y la carga corre aparte con su
propia sesión de base de datos (misma organización, mismo usuario para la
auditoría). La pantalla consulta el avance cada pocos segundos.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import UUID

from fastapi import BackgroundTasks, Request
from sqlalchemy.orm import Session

from app.auditoria import CLAVE_CONTEXTO
from app.database import SessionLocal
from app.models.trabajo import Trabajo
from app.models.usuario import Usuario
from app.security import ip_cliente
from app.tenancy import activar_organizacion

log = logging.getLogger("cartera.trabajos")

# Un trabajo "procesando" por más de esto se dio por cortado (el servidor se reinició).
LIMITE = timedelta(hours=2)


def lanzar(tareas: BackgroundTasks, db: Session, usuario: Usuario, request: Request,
           tipo: str, archivo: str, funcion: Callable) -> Trabajo:
    """funcion(db, usuario, avance) -> dict con el resultado; corre en segundo plano."""
    trabajo = Trabajo(tipo=tipo, archivo=archivo[:255], creado_por=usuario.id)
    db.add(trabajo)
    db.commit()
    db.refresh(trabajo)
    tareas.add_task(_ejecutar, trabajo.id, usuario.organizacion_id, usuario.id, ip_cliente(request), funcion)
    return trabajo


def _ejecutar(trabajo_id: UUID, organizacion_id: UUID, usuario_id: UUID, ip, funcion: Callable) -> None:
    db = SessionLocal()
    db.expire_on_commit = False
    try:
        activar_organizacion(db, organizacion_id)
        db.info[CLAVE_CONTEXTO] = {"usuario_id": usuario_id, "ip": ip}
        trabajo = db.get(Trabajo, trabajo_id)
        usuario = db.get(Usuario, usuario_id)
        trabajo.estado = "procesando"
        db.commit()

        def avance(hechas: int, total: int | None = None) -> None:
            trabajo.procesadas = hechas
            if total is not None:
                trabajo.total = total
                db.commit()

        resultado = funcion(db, usuario, avance)
        trabajo.estado = "terminado"
        trabajo.resultado = resultado
        trabajo.terminado_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as e:  # noqa: BLE001 — el error queda en el trabajo, no se pierde
        db.rollback()
        if not isinstance(e, ValueError):
            log.exception("Falló el trabajo %s", trabajo_id)
        trabajo = db.get(Trabajo, trabajo_id)
        if trabajo is not None:
            trabajo.estado = "error"
            trabajo.resultado = {"error": str(e) if isinstance(e, ValueError)
                                 else "Error inesperado durante la carga. Lo cargado hasta el último "
                                      "guardado quedó; revisa y vuelve a subir el archivo."}
            trabajo.terminado_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


def revisar_cortado(db: Session, trabajo: Trabajo) -> Trabajo:
    """Si el servidor se reinició a mitad de camino, el trabajo queda marcado como cortado."""
    if trabajo.estado in ("en_cola", "procesando") and trabajo.created_at \
            and datetime.now(timezone.utc) - trabajo.created_at > LIMITE:
        trabajo.estado = "error"
        trabajo.resultado = {"error": "La carga se interrumpió (el servidor se reinició). "
                                      "Lo guardado hasta ese momento quedó; vuelve a subir el archivo: "
                                      "lo que ya estaba se salta."}
        db.commit()
    return trabajo

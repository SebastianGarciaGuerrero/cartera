"""
Ciclo de vida de las sesiones, cookie del refresh token, límite de
intentos por IP y bitácora de accesos.

Todo lo de este módulo corre en MODO SISTEMA (antes de conocer o validar la
organización), por eso nunca se llama desde un endpoint ya autenticado sin
pasar explícitamente la sesión de base de datos.
"""

import hashlib
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, Request, Response, status
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.config import settings
from app.models.seguridad import EventoAcceso, Sesion
from app.models.usuario import Usuario

COOKIE_REFRESH = "cartera_refresh"
RUTA_COOKIE = "/api/auth"
# Si dos pestañas refrescan a la vez, la segunda presenta el token recién
# rotado. Dentro de esta ventana no se toma como robo.
GRACIA_ROTACION = timedelta(seconds=30)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def nuevo_token() -> str:
    return secrets.token_urlsafe(32)  # 256 bits


# ============================================================
# Sesiones
# ============================================================

def crear_sesion(db: Session, usuario: Usuario, request: Request) -> tuple[Sesion, str]:
    token = nuevo_token()
    sesion = Sesion(
        usuario_id=usuario.id,
        organizacion_id=usuario.organizacion_id,
        refresh_hash=hash_token(token),
        expira_at=_ahora() + timedelta(days=settings.sesion_maxima_dias),
        ip=_ip(request),
        user_agent=(request.headers.get("user-agent") or "")[:300],
    )
    db.add(sesion)
    db.flush()
    return sesion, token


def rotar_sesion(db: Session, token: str) -> tuple[Sesion, Optional[str]]:
    """
    Valida un refresh token y lo cambia por uno nuevo. Devuelve la sesión y
    el token nuevo (None si se aceptó dentro de la ventana de gracia: el
    navegador ya tiene la cookie nueva).
    Lanza 401 si el token no sirve; si es un token YA ROTADO fuera de la
    ventana de gracia, revoca la sesión completa (posible robo).
    """
    h = hash_token(token)
    ahora = _ahora()
    sesion = db.query(Sesion).filter(Sesion.refresh_hash == h).with_for_update().first()
    en_gracia = False
    if sesion is None:
        sesion = (
            db.query(Sesion).filter(Sesion.refresh_anterior_hash == h)
            .with_for_update().first()
        )
        if sesion is None:
            raise _401()
        if sesion.revocada_at is None and ahora - sesion.ultimo_uso_at <= GRACIA_ROTACION:
            en_gracia = True
        else:
            revocar(db, sesion, "reutilizacion_refresh")
            registrar_evento(db, "refresh_reutilizado", False, usuario_id=sesion.usuario_id,
                             organizacion_id=sesion.organizacion_id)
            db.commit()
            raise _401()

    if sesion.revocada_at is not None or sesion.expira_at <= ahora:
        raise _401()
    if ahora - sesion.ultimo_uso_at > timedelta(hours=settings.sesion_inactividad_horas):
        revocar(db, sesion, "inactividad")
        db.commit()
        raise _401()

    if en_gracia:
        return sesion, None

    nuevo = nuevo_token()
    sesion.refresh_anterior_hash = sesion.refresh_hash
    sesion.refresh_hash = hash_token(nuevo)
    sesion.ultimo_uso_at = ahora
    return sesion, nuevo


def revocar(db: Session, sesion: Sesion, motivo: str) -> None:
    if sesion.revocada_at is None:
        sesion.revocada_at = _ahora()
        sesion.motivo_revocacion = motivo


def revocar_todas(db: Session, usuario_id, motivo: str, excepto=None) -> None:
    """Cierra todas las sesiones del usuario (cambio de contraseña, desactivación)."""
    q = update(Sesion).where(Sesion.usuario_id == usuario_id, Sesion.revocada_at.is_(None))
    if excepto is not None:
        q = q.where(Sesion.id != excepto)
    db.execute(q.values(revocada_at=_ahora(), motivo_revocacion=motivo))


def _401() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Sesión vencida. Vuelve a iniciar sesión.",
    )


# ============================================================
# Cookie
# ============================================================

def poner_cookie_refresh(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_REFRESH,
        token,
        max_age=settings.sesion_maxima_dias * 86400,
        httponly=True,
        secure=settings.cookie_segura,
        samesite="strict",
        path=RUTA_COOKIE,
    )


def borrar_cookie_refresh(response: Response) -> None:
    response.delete_cookie(
        COOKIE_REFRESH, path=RUTA_COOKIE, httponly=True,
        secure=settings.cookie_segura, samesite="strict",
    )


def exigir_cabecera_csrf(request: Request) -> None:
    """
    Los endpoints que usan la cookie exigen una cabecera que un formulario
    de otro sitio no puede enviar (defensa extra sobre SameSite=Strict).
    """
    if request.headers.get("x-requested-with") != "cartera":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solicitud rechazada.")


# ============================================================
# Límite de intentos por IP (ventana deslizante en memoria)
# ============================================================
# Complementa el bloqueo por cuenta (que vive en la base y vale para todas
# las réplicas). Este frena a quien prueba MUCHAS cuentas desde una IP.

_intentos_ip: dict[str, deque] = defaultdict(deque)
_candado_ip = threading.Lock()


def controlar_limite_ip(request: Request, accion: str) -> None:
    clave = f"{accion}:{_ip(request)}"
    ahora = time.monotonic()
    ventana = settings.limite_ip_ventana_segundos
    with _candado_ip:
        cola = _intentos_ip[clave]
        while cola and ahora - cola[0] > ventana:
            cola.popleft()
        if len(cola) >= settings.limite_ip_intentos:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Demasiados intentos desde tu conexión. Espera unos minutos.",
                headers={"Retry-After": str(ventana)},
            )
        cola.append(ahora)


def reiniciar_limites_ip() -> None:
    """Solo para tests."""
    with _candado_ip:
        _intentos_ip.clear()


# ============================================================
# Bitácora de accesos
# ============================================================

def _ip(request: Optional[Request]) -> Optional[str]:
    return request.client.host if request is not None and request.client else None


def registrar_evento(
    db: Session,
    evento: str,
    exito: bool,
    *,
    request: Optional[Request] = None,
    usuario_id=None,
    organizacion_id=None,
    email: Optional[str] = None,
    detalle: Optional[dict] = None,
) -> None:
    db.add(EventoAcceso(
        evento=evento,
        exito=exito,
        usuario_id=usuario_id,
        organizacion_id=organizacion_id,
        email=(email or None) and email[:150],
        ip=_ip(request),
        user_agent=((request.headers.get("user-agent") or "")[:300]) if request else None,
        detalle=detalle,
    ))

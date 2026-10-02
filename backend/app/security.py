"""
Seguridad: contraseñas, tokens de acceso y dependencias de autorización.

Flujo de autenticación (ver routers/auth.py):
  1. POST /api/auth/login con email + contraseña (+ código 2FA si lo tiene).
  2. Se crea una SESIÓN en la base y se devuelven dos credenciales:
       - access token (JWT, 15 min): viaja en el header Authorization y el
         navegador lo guarda SOLO en memoria (no en localStorage, así un XSS
         no puede robarlo de forma persistente).
       - refresh token (aleatorio): va en una cookie httpOnly + Secure +
         SameSite=Strict, que JavaScript no puede leer. Se rota en cada uso.
  3. Cada petición: get_current_user valida el JWT, verifica que la sesión
     siga viva (logout y cambio de contraseña la cortan al instante) y fija
     la organización de la petición (app/tenancy.py).

Contraseñas: Argon2id (recomendación OWASP). Los hashes bcrypt heredados se
siguen aceptando y se re-hashean a Argon2id en el siguiente login exitoso.
"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID, uuid4

import bcrypt
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auditoria import CLAVE_CONTEXTO
from app.config import settings
from app.database import get_db
from app.models.organizacion import Organizacion
from app.models.seguridad import Sesion
from app.models.usuario import Usuario
from app.tenancy import activar_organizacion, modo_sistema


# ============================================================
# Contraseñas
# ============================================================

_hasher = PasswordHasher()  # Argon2id, parámetros RFC 9106 (64 MiB, t=3, p=4)

# Hash de una contraseña al azar: se verifica contra él cuando el email no
# existe, para que la respuesta tarde lo mismo y no revele qué emails hay.
_HASH_SEÑUELO = _hasher.hash(secrets.token_urlsafe(16))

PASSWORD_MIN = 12
PASSWORD_MAX = 128

# Las más usadas en Chile y en el mundo (no exhaustiva: el largo mínimo hace
# el grueso del trabajo).
_PASSWORDS_COMUNES = {
    "123456789012", "1234567890123", "qwertyuiopas", "contraseña123", "contrasena123",
    "password1234", "password12345", "passwordpassword", "123456123456", "111111111111",
    "000000000000", "abcdefghijkl", "abc123abc123", "iloveyou1234", "chile1234567",
    "colocolo1234", "santiago1234", "admin1234567", "administrador", "bienvenido123",
    "cobranza1234", "cartera12345", "qwerty123456", "asdfghjklñ12", "1q2w3e4r5t6y",
}


def validar_password(password: str, email: Optional[str] = None) -> None:
    """Política de contraseñas (NIST 800-63B): largo, no común, no el email."""
    if len(password) < PASSWORD_MIN:
        raise ValueError(f"La contraseña debe tener al menos {PASSWORD_MIN} caracteres.")
    if len(password) > PASSWORD_MAX:
        raise ValueError(f"La contraseña no puede superar {PASSWORD_MAX} caracteres.")
    if password.lower() in _PASSWORDS_COMUNES or len(set(password)) < 4:
        raise ValueError("Esa contraseña es demasiado común. Elige otra.")
    if email:
        local = email.split("@")[0].lower()
        if len(local) >= 4 and local in password.lower():
            raise ValueError("La contraseña no puede contener tu email.")


def hashear_password(plano: str) -> str:
    return _hasher.hash(plano)


def verificar_password(plano: str, hasheado: Optional[str]) -> tuple[bool, bool]:
    """
    Devuelve (es_correcta, necesita_rehash). Acepta Argon2id y bcrypt
    heredado (este último siempre pide re-hash).
    """
    if not hasheado:
        _verificar_señuelo(plano)
        return False, False
    if hasheado.startswith("$2"):
        try:
            ok = bcrypt.checkpw(plano.encode("utf-8")[:72], hasheado.encode("utf-8"))
        except ValueError:
            return False, False
        return ok, ok
    try:
        _hasher.verify(hasheado, plano)
    except (VerificationError, InvalidHashError):
        return False, False
    return True, _hasher.check_needs_rehash(hasheado)


def _verificar_señuelo(plano: str) -> None:
    try:
        _hasher.verify(_HASH_SEÑUELO, plano)
    except VerificationError:
        pass


def tiempo_constante_sin_usuario(plano: str) -> None:
    """Gasta el mismo tiempo que una verificación real (email inexistente)."""
    _verificar_señuelo(plano)


# ============================================================
# Tokens JWT
# ============================================================

def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def crear_access_token(usuario: Usuario, sesion_id: UUID) -> str:
    ahora = _ahora()
    claims = {
        "sub": str(usuario.id),
        "org": str(usuario.organizacion_id),
        "sid": str(sesion_id),
        "rol": usuario.rol_nombre,
        "typ": "access",
        "iss": settings.jwt_emisor,
        "aud": settings.jwt_audiencia,
        "iat": ahora,
        "nbf": ahora,
        "exp": ahora + timedelta(minutes=settings.access_token_minutos),
        "jti": uuid4().hex,
    }
    return jwt.encode(claims, settings.secret_key, algorithm="HS256")


def crear_token_mfa_pendiente(usuario: Usuario) -> str:
    """Token de 5 minutos que solo sirve para completar el segundo factor."""
    ahora = _ahora()
    claims = {
        "sub": str(usuario.id),
        "typ": "mfa",
        "iss": settings.jwt_emisor,
        "aud": settings.jwt_audiencia,
        "iat": ahora,
        "exp": ahora + timedelta(minutes=5),
        "jti": uuid4().hex,
    }
    return jwt.encode(claims, settings.secret_key, algorithm="HS256")


def decodificar_token(token: str, tipo: str) -> dict:
    """Valida firma, emisor, audiencia, vencimiento y tipo. Lanza ValueError."""
    try:
        claims = jwt.decode(
            token,
            settings.secret_key,
            algorithms=["HS256"],  # fijo: nunca se acepta el algoritmo del token
            audience=settings.jwt_audiencia,
            issuer=settings.jwt_emisor,
            options={"require": ["exp", "iat", "sub", "typ", "jti"]},
        )
    except jwt.PyJWTError as e:
        raise ValueError(str(e)) from e
    if claims.get("typ") != tipo:
        raise ValueError("Tipo de token incorrecto")
    return claims


# ============================================================
# Dependencias de FastAPI
# ============================================================

_bearer = HTTPBearer(auto_error=False)

_NO_AUTENTICADO = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Sesión no válida o vencida. Vuelve a iniciar sesión.",
    headers={"WWW-Authenticate": "Bearer"},
)


def ip_cliente(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


def get_current_user(
    request: Request,
    credenciales: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Usuario:
    """
    Valida el access token y devuelve el usuario. Además deja la sesión de
    base de datos fijada a la organización del usuario (ORM + RLS) y el
    contexto de auditoría (quién y desde qué IP).
    """
    if credenciales is None or credenciales.scheme.lower() != "bearer":
        raise _NO_AUTENTICADO
    try:
        claims = decodificar_token(credenciales.credentials, "access")
        usuario_id = UUID(claims["sub"])
        sesion_id = UUID(claims["sid"])
    except (ValueError, KeyError):
        raise _NO_AUTENTICADO

    # Validación en modo sistema: todavía no sabemos la organización.
    modo_sistema(db)
    sesion = db.get(Sesion, sesion_id)
    if (
        sesion is None
        or sesion.usuario_id != usuario_id
        or sesion.revocada_at is not None
        or sesion.expira_at <= _ahora()
    ):
        raise _NO_AUTENTICADO

    usuario = db.get(Usuario, usuario_id)
    if usuario is None or not usuario.activo:
        raise _NO_AUTENTICADO
    organizacion = db.get(Organizacion, usuario.organizacion_id)
    if organizacion is None or not organizacion.habilitada:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La cuenta de tu organización está suspendida. Contacta a soporte.",
        )

    activar_organizacion(db, usuario.organizacion_id)
    db.info[CLAVE_CONTEXTO] = {"usuario_id": usuario.id, "ip": ip_cliente(request)}
    request.state.usuario = usuario
    request.state.organizacion = organizacion
    return usuario


METODOS_ESCRITURA = {"POST", "PUT", "PATCH", "DELETE"}

# Roles internos del estudio. 'mandante' (portal de clientes) NO entra a la
# API interna: tiene sus propios endpoints de solo lectura.
ROLES_INTERNOS = {"admin", "supervisor", "operador", "abogado", "procurador", "viewer"}


def usuario_autorizado(
    request: Request,
    usuario: Usuario = Depends(get_current_user),
) -> Usuario:
    """
    Dependencia estándar de los módulos de negocio: usuario interno del
    estudio; el rol 'viewer' es de SOLO LECTURA.
    """
    if usuario.rol_nombre not in ROLES_INTERNOS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tu usuario no tiene acceso a esta sección.",
        )
    if request.method in METODOS_ESCRITURA and usuario.rol_nombre == "viewer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El rol 'viewer' es de solo lectura: no puede crear ni modificar registros",
        )
    return usuario


def requiere_roles(*roles: str):
    """Dependencia: exige uno de los roles indicados."""
    def _dependencia(usuario: Usuario = Depends(get_current_user)) -> Usuario:
        if usuario.rol_nombre not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para esta operación.",
            )
        return usuario
    return _dependencia


def require_admin(usuario: Usuario = Depends(get_current_user)) -> Usuario:
    """Dependencia para endpoints SOLO-ADMIN de la organización."""
    if usuario.rol_nombre != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere rol de administrador para esta operación",
        )
    return usuario

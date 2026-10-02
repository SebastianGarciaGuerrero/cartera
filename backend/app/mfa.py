"""
Segundo factor de autenticación (2FA) con TOTP: los códigos de 6 dígitos de
Google Authenticator, Microsoft Authenticator, 1Password, etc.

  - La semilla se guarda CIFRADA en la base (Fernet / AES-128-CBC + HMAC):
    un respaldo filtrado de la base no basta para generar códigos.
  - Un código ya usado no se acepta de nuevo (anti-replay).
  - Al activarlo se entregan 10 códigos de recuperación de un solo uso
    (se guarda solo su hash) por si se pierde el teléfono.
"""

import base64
import hashlib
import secrets
import time
from typing import Optional

import pyotp
import segno
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import settings
from app.models.usuario import Usuario

EMISOR = "Cartera"
PERIODO = 30


def _fernet() -> Fernet:
    if settings.clave_cifrado:
        return Fernet(settings.clave_cifrado.encode())
    clave = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=b"cartera-cifrado-v1"
    ).derive(settings.secret_key.encode())
    return Fernet(base64.urlsafe_b64encode(clave))


def cifrar(texto: str) -> str:
    return _fernet().encrypt(texto.encode()).decode()


def descifrar(texto: str) -> Optional[str]:
    try:
        return _fernet().decrypt(texto.encode()).decode()
    except InvalidToken:
        return None


def nueva_semilla() -> str:
    return pyotp.random_base32()


def uri_configuracion(semilla: str, email: str) -> str:
    return pyotp.TOTP(semilla).provisioning_uri(name=email, issuer_name=EMISOR)


def qr_svg(uri: str) -> str:
    """QR como data URI SVG (se genera en el servidor: la semilla no sale a terceros)."""
    return segno.make(uri, error="m").svg_data_uri(scale=5, border=2)


def verificar_codigo(usuario: Usuario, codigo: str, semilla: Optional[str] = None) -> bool:
    """
    Verifica un código TOTP (acepta ±1 intervalo por desfase del reloj) y
    registra el intervalo usado para que no se pueda reusar.
    """
    codigo = (codigo or "").strip().replace(" ", "")
    if not codigo.isdigit() or len(codigo) != 6:
        return False
    if semilla is None:
        if not usuario.mfa_secreto_cifrado:
            return False
        semilla = descifrar(usuario.mfa_secreto_cifrado)
        if semilla is None:
            return False
    totp = pyotp.TOTP(semilla)
    paso_actual = int(time.time()) // PERIODO
    for desfase in (-1, 0, 1):
        paso = paso_actual + desfase
        if usuario.mfa_ultimo_paso is not None and paso <= usuario.mfa_ultimo_paso:
            continue  # ya usado (o anterior al último usado)
        if secrets.compare_digest(totp.at(paso * PERIODO), codigo):
            usuario.mfa_ultimo_paso = paso
            return True
    return False


def _hash_codigo(codigo: str) -> str:
    return hashlib.sha256(codigo.replace("-", "").lower().encode()).hexdigest()


def generar_codigos_recuperacion() -> tuple[list[str], list[str]]:
    """Devuelve (códigos para mostrar UNA vez, hashes para guardar)."""
    codigos = []
    for _ in range(10):
        crudo = secrets.token_hex(5)  # 10 caracteres hex = 40 bits
        codigos.append(f"{crudo[:5]}-{crudo[5:]}")
    return codigos, [_hash_codigo(c) for c in codigos]


def usar_codigo_recuperacion(usuario: Usuario, codigo: str) -> bool:
    h = _hash_codigo((codigo or "").strip())
    restantes = list(usuario.mfa_codigos_recuperacion or [])
    for i, guardado in enumerate(restantes):
        if secrets.compare_digest(guardado, h):
            del restantes[i]
            usuario.mfa_codigos_recuperacion = restantes  # reasignar: JSONB no detecta mutaciones
            return True
    return False

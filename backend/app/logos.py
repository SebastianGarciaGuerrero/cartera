"""
Validación del logo de una organización: solo PNG o JPG reales (se mira
la firma del archivo, no la extensión) y de hasta 1 MB.
"""

from typing import Optional

TAMANO_MAXIMO = 1024 * 1024


class ErrorLogo(ValueError):
    pass


def tipo_de_imagen(datos: bytes) -> Optional[str]:
    if datos.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if datos.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return None


def validar_logo(datos: bytes) -> str:
    """Devuelve el tipo MIME o lanza ErrorLogo."""
    if not datos:
        raise ErrorLogo("El archivo está vacío.")
    if len(datos) > TAMANO_MAXIMO:
        raise ErrorLogo("El logo no puede pesar más de 1 MB. Achícalo o comprímelo.")
    tipo = tipo_de_imagen(datos)
    if tipo is None:
        raise ErrorLogo("El logo debe ser una imagen PNG o JPG.")
    return tipo

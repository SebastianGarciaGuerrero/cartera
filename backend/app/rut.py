"""
RUT chileno: validación del dígito verificador (módulo 11) y formato único.

Formato canónico guardado en la base: sin puntos, con guion y DV en
mayúscula → '12345678-5', '7654321-K'. Así "12.345.678-5" y "123456785"
se reconocen como el mismo deudor.
"""

import re
from typing import Annotated

from pydantic import AfterValidator


def calcular_dv(cuerpo: int) -> str:
    suma, factor = 0, 2
    while cuerpo:
        suma += (cuerpo % 10) * factor
        cuerpo //= 10
        factor = 2 if factor == 7 else factor + 1
    resto = 11 - (suma % 11)
    return {11: "0", 10: "K"}.get(resto, str(resto))


def normalizar_rut(texto: str) -> str:
    """'12.345.678-5' → '12345678-5'. Lanza ValueError si el RUT no es válido."""
    limpio = re.sub(r"[.\s-]", "", str(texto or "")).upper()
    if not re.fullmatch(r"\d{1,8}[\dK]", limpio):
        raise ValueError("RUT con formato inválido (ej. 12.345.678-5)")
    cuerpo, dv = limpio[:-1], limpio[-1]
    if int(cuerpo) < 100_000:
        raise ValueError("RUT inválido")
    if calcular_dv(int(cuerpo)) != dv:
        raise ValueError("RUT inválido: el dígito verificador no corresponde")
    return f"{int(cuerpo)}-{dv}"


def rut_con_puntos(rut: str) -> str:
    """'12345678-5' → '12.345.678-5' (para documentos)."""
    if not rut:
        return "—"
    cuerpo, _, dv = str(rut).partition("-")
    cuerpo = cuerpo.replace(".", "")
    con_puntos = f"{int(cuerpo):,}".replace(",", ".") if cuerpo.isdigit() else cuerpo
    return f"{con_puntos}-{dv}" if dv else con_puntos


# Tipo para schemas de ENTRADA: valida y normaliza.
Rut = Annotated[str, AfterValidator(normalizar_rut)]

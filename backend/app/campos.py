"""
Validación de los campos personalizados (datos_extra de cobranzas y deudores).

Cada organización define sus campos (models/campo_personalizado.py). Acá se
valida que lo que llega calce con esa definición: que el campo exista y
aplique a ese mandante, que el valor tenga el tipo correcto y que los
obligatorios vengan. Los valores se guardan en formato JSON simple:
texto → str, número/monto → str decimal, fecha → 'AAAA-MM-DD', sí/no → bool.
"""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.campo_personalizado import CampoPersonalizado


class ErrorCampo(ValueError):
    pass


def campos_aplicables(db: Session, entidad: str, cliente_id: Optional[UUID] = None):
    campos = (
        db.query(CampoPersonalizado)
        .filter(CampoPersonalizado.entidad == entidad, CampoPersonalizado.activo.is_(True))
        .order_by(CampoPersonalizado.orden, CampoPersonalizado.etiqueta)
        .all()
    )
    return [c for c in campos if c.cliente_id is None or c.cliente_id == cliente_id]


def convertir_valor(campo: CampoPersonalizado, valor):
    """Convierte y valida un valor según el tipo del campo."""
    etiqueta = campo.etiqueta
    if campo.tipo == "texto":
        texto = str(valor).strip()
        if len(texto) > 500:
            raise ErrorCampo(f"«{etiqueta}» admite hasta 500 caracteres")
        return texto
    if campo.tipo in ("numero", "monto"):
        try:
            numero = Decimal(str(valor).replace(" ", ""))
        except InvalidOperation:
            raise ErrorCampo(f"«{etiqueta}» debe ser un número")
        if not numero.is_finite():
            raise ErrorCampo(f"«{etiqueta}» debe ser un número")
        if campo.tipo == "monto":
            numero = numero.quantize(Decimal("0.01"))
        return str(numero)
    if campo.tipo == "fecha":
        if isinstance(valor, datetime):
            return valor.date().isoformat()
        if isinstance(valor, date):
            return valor.isoformat()
        try:
            return date.fromisoformat(str(valor).strip()[:10]).isoformat()
        except ValueError:
            raise ErrorCampo(f"«{etiqueta}» debe ser una fecha AAAA-MM-DD")
    if campo.tipo == "seleccion":
        opciones = [str(o) for o in (campo.opciones or [])]
        texto = str(valor).strip()
        if texto not in opciones:
            raise ErrorCampo(f"«{etiqueta}» debe ser una de: {', '.join(opciones)}")
        return texto
    if campo.tipo == "si_no":
        if isinstance(valor, bool):
            return valor
        texto = str(valor).strip().lower()
        if texto in ("si", "sí", "true", "1", "s", "x"):
            return True
        if texto in ("no", "false", "0", "n"):
            return False
        raise ErrorCampo(f"«{etiqueta}» debe ser sí o no")
    raise ErrorCampo(f"Tipo de campo desconocido: {campo.tipo}")


def validar_datos_extra(
    db: Session,
    entidad: str,
    datos: Optional[dict],
    *,
    cliente_id: Optional[UUID] = None,
    actuales: Optional[dict] = None,
) -> dict:
    """
    Devuelve el datos_extra final ya validado. Si se pasan `actuales`
    (actualización), se mezclan: un valor None o "" borra esa clave.
    """
    campos = {c.clave: c for c in campos_aplicables(db, entidad, cliente_id)}
    resultado = dict(actuales or {})
    for clave, valor in (datos or {}).items():
        campo = campos.get(clave)
        if campo is None:
            raise ErrorCampo(f"El campo personalizado '{clave}' no existe o no aplica")
        if valor is None or (isinstance(valor, str) and not valor.strip()):
            resultado.pop(clave, None)
            continue
        resultado[clave] = convertir_valor(campo, valor)

    faltantes = [c.etiqueta for c in campos.values() if c.obligatorio and c.clave not in resultado]
    if faltantes:
        raise ErrorCampo(f"Faltan campos obligatorios: {', '.join(faltantes)}")
    return resultado

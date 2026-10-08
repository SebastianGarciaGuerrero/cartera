"""
Planes del SaaS y las funciones que habilita cada uno.

El plan de cada organización está en organizaciones.plan. Además, la
plataforma puede activarle funciones sueltas a una organización
(configuracion["funciones_extra"]), por ejemplo para una prueba o un
precio especial, sin cambiarle el plan.

Los endpoints de un módulo pagado usan `requiere_funcion("judicial")`.
"""

from fastapi import Depends, HTTPException, Request, status

from app.models.organizacion import Organizacion
from app.security import get_current_user

_BASE = {
    "cobranzas", "deudores", "gestiones", "acuerdos", "pagos", "informes",
    "carga_masiva", "documentos", "campos_personalizados", "agenda",
    "mensaje_pago",  # mensaje listo con datos de transferencia (copiar/abrir)
}
_PROFESIONAL = _BASE | {
    "judicial", "portal_mandantes", "portal_deudor", "recordatorios", "comunicaciones",
}
_PREMIUM = _PROFESIONAL | {
    "calculadora_369", "envio_automatico", "pagos_en_linea", "api",
}

FUNCIONES_POR_PLAN = {
    "base": _BASE,
    "profesional": _PROFESIONAL,
    "premium": _PREMIUM,
}

NOMBRE_FUNCION = {
    "judicial": "Módulo judicial",
    "portal_mandantes": "Portal de clientes",
    "portal_deudor": "Portal del deudor",
    "recordatorios": "Recordatorios automáticos",
    "comunicaciones": "Comunicaciones masivas",
    "calculadora_369": "Calculadora 3-6-9 y acuerdos asistidos",
    "envio_automatico": "Envío automático de cobranza",
    "pagos_en_linea": "Pagos en línea",
    "api": "API para integraciones",
}


def funciones_de(org: Organizacion) -> set[str]:
    funciones = set(FUNCIONES_POR_PLAN.get(org.plan, _BASE))
    extra = (org.configuracion or {}).get("funciones_extra") or []
    return funciones | {f for f in extra if isinstance(f, str)}


def requiere_funcion(funcion: str):
    """Dependencia: la organización del usuario debe tener la función."""
    def _dependencia(request: Request, _usuario=Depends(get_current_user)):
        org: Organizacion = request.state.organizacion
        if funcion not in funciones_de(org):
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Tu plan no incluye «{NOMBRE_FUNCION.get(funcion, funcion)}». "
                       "Puedes activarlo desde Configuración → Plan.",
            )
    return _dependencia

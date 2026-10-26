"""
Qué puede hacer cada rol dentro del estudio.

Todos los roles internos (salvo 'viewer', de solo lectura) trabajan sus
casos: registran gestiones, promesas, acuerdos, abonos y gastos de cada
cobranza, y pueden recomendar pasar una cobranza a demanda. Lo que está
aquí es lo que NO es para todos:

  cobranzas_crear      ingresar cobranzas una por una
  carga_masiva         carga masiva de cobranzas
  gestiones_masivas    carga masiva de gestiones
  clientes_editar      crear y editar clientes (mandantes) y sus filiales
  judicial_causas      presentar demandas, juntar cobranzas en una causa, terminarla
  judicial_tramites    registrar trámites y embargos
  ver_totales          totales de toda la cartera: panel general, informes,
                       resumen por etapa, gastos por cliente
  gastos_rendir        rendir y reembolsar gastos a los clientes

Cada estudio puede ajustar la tabla desde Configuración → Roles y permisos
(se guarda en organizaciones.configuracion["permisos"]). El administrador
siempre lo puede todo.
"""

from fastapi import Depends, HTTPException, Request, status

from app.models.organizacion import Organizacion
from app.models.usuario import Usuario
from app.security import get_current_user

PERMISOS = {
    "cobranzas_crear": "Ingresar cobranzas",
    "carga_masiva": "Carga masiva de cobranzas",
    "gestiones_masivas": "Carga masiva de gestiones",
    "clientes_editar": "Crear y editar clientes",
    "judicial_causas": "Presentar demandas y cerrar causas",
    "judicial_tramites": "Registrar trámites y embargos",
    "ver_totales": "Ver los totales de toda la cartera",
    "gastos_rendir": "Rendir y reembolsar gastos",
}

# Los roles que se pueden ajustar (el admin siempre tiene todo).
ROLES_AJUSTABLES = ("supervisor", "abogado", "procurador", "operador", "viewer")

POR_DEFECTO: dict[str, set[str]] = {
    "supervisor": set(PERMISOS),
    "abogado": {"cobranzas_crear", "judicial_causas", "judicial_tramites"},
    "procurador": {"judicial_tramites"},
    "operador": {"cobranzas_crear"},
    "viewer": set(),
}


def permisos_de(rol: str | None, org: Organizacion | None) -> set[str]:
    """Permisos del rol en la organización (lo ajustado por el estudio, o el defecto)."""
    if rol == "admin":
        return set(PERMISOS)
    ajustes = ((org.configuracion if org else None) or {}).get("permisos") or {}
    if rol in ajustes and isinstance(ajustes[rol], list):
        return {p for p in ajustes[rol] if p in PERMISOS}
    return set(POR_DEFECTO.get(rol or "", set()))


def tiene_permiso(request: Request, usuario: Usuario, permiso: str) -> bool:
    return permiso in permisos_de(usuario.rol_nombre, getattr(request.state, "organizacion", None))


def requiere_permiso(permiso: str):
    """Dependencia: el rol del usuario debe tener el permiso."""
    def _dependencia(request: Request, usuario: Usuario = Depends(get_current_user)) -> Usuario:
        if not tiene_permiso(request, usuario, permiso):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Tu rol no permite: {PERMISOS[permiso].lower()}. Pídeselo a la administración.",
            )
        return usuario
    return _dependencia

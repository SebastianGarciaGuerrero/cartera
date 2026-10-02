"""
Aislamiento entre organizaciones (multi-tenant).

Dos capas independientes; cualquiera de las dos sola ya impide ver datos de
otra organización:

1. ORM (este módulo): toda consulta a un modelo con organizacion_id recibe
   automáticamente `WHERE organizacion_id = <la de la sesión>`, y todo
   objeto nuevo recibe la organización de la sesión. Ningún router tiene
   que acordarse de filtrar.

2. PostgreSQL (RLS, migración 0005): al empezar cada transacción
   autenticada se hace `SET LOCAL ROLE cartera_app` y se fija
   `app.organizacion_id`. Las políticas de la base filtran también las
   consultas SQL escritas a mano (vistas, reportes) y rechazan escrituras
   con otra organización.

Estados de una sesión:
  - con organización: lo normal en un endpoint autenticado.
  - modo sistema: sin filtro, como dueño de las tablas. Solo para el login,
    la validación del token, tareas programadas y comandos de consola.
  - ninguno de los dos: falla cerrado, las tablas de negocio se ven vacías y
    no se puede insertar en ellas.
"""

from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import Column, ForeignKey, event, or_, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Session, declared_attr, with_loader_criteria

from app.config import settings

CLAVE_ORGANIZACION = "organizacion_id"
CLAVE_SISTEMA = "modo_sistema"

# Valor imposible para cuando no hay organización: la consulta no devuelve
# filas (en vez de comparar contra NULL, que cambiaría la forma del SQL).
_SIN_ORGANIZACION = UUID(int=0)


class TenantMixin:
    """Modelo que pertenece a una organización (organizacion_id NOT NULL)."""

    @declared_attr
    def organizacion_id(cls):
        return Column(PGUUID(as_uuid=True), ForeignKey("organizaciones.id"), nullable=False)


class TenantGlobalMixin:
    """
    Catálogo mixto: filas de sistema (organizacion_id NULL, visibles para
    todos) más filas propias de cada organización.
    """

    @declared_attr
    def organizacion_id(cls):
        return Column(PGUUID(as_uuid=True), ForeignKey("organizaciones.id"), nullable=True)


class ErrorOrganizacion(RuntimeError):
    """Intento de escribir sin organización o en una organización ajena."""


def organizacion_actual(db: Session):
    return db.info.get(CLAVE_ORGANIZACION)


def activar_organizacion(db: Session, organizacion_id: UUID) -> None:
    """Fija la organización de la sesión (capa ORM y capa RLS)."""
    db.info[CLAVE_ORGANIZACION] = organizacion_id
    db.info.pop(CLAVE_SISTEMA, None)
    if db.in_transaction():
        # La transacción ya empezó (ej. se leyó el usuario para validar el
        # token): se fija sobre la conexión en curso. Las transacciones
        # siguientes lo reciben en after_begin.
        _fijar_en_conexion(db.connection(), organizacion_id)


def modo_sistema(db: Session) -> None:
    """La sesión opera sin filtro (login, tareas programadas, consola)."""
    db.info[CLAVE_SISTEMA] = True


@contextmanager
def sesion_sistema():
    """
    Sesión de base de datos aparte, en modo sistema. Para tablas que el rol
    de la app no ve (sesiones, tokens) desde un endpoint ya autenticado, y
    para tareas programadas.
    """
    from app.database import SessionLocal

    db = SessionLocal()
    modo_sistema(db)
    try:
        yield db
    finally:
        db.close()


def _fijar_en_conexion(conexion, organizacion_id: UUID) -> None:
    if settings.rol_app:
        conexion.exec_driver_sql(f'SET LOCAL ROLE "{settings.rol_app}"')
    conexion.execute(
        text("SELECT set_config('app.organizacion_id', :o, true)"),
        {"o": str(organizacion_id)},
    )


@event.listens_for(Session, "after_begin")
def _al_iniciar_transaccion(session, transaction, connection):
    organizacion_id = session.info.get(CLAVE_ORGANIZACION)
    if organizacion_id is not None:
        _fijar_en_conexion(connection, organizacion_id)


@event.listens_for(Session, "do_orm_execute")
def _filtrar_por_organizacion(estado):
    if not (estado.is_select or estado.is_update or estado.is_delete):
        return
    if estado.is_column_load or estado.is_relationship_load:
        return  # heredan el criterio de la consulta que los originó
    if estado.session.info.get(CLAVE_SISTEMA):
        return
    org = estado.session.info.get(CLAVE_ORGANIZACION) or _SIN_ORGANIZACION
    estado.statement = estado.statement.options(
        with_loader_criteria(
            TenantMixin,
            lambda cls: cls.organizacion_id == org,
            include_aliases=True,
        ),
        with_loader_criteria(
            TenantGlobalMixin,
            lambda cls: or_(cls.organizacion_id.is_(None), cls.organizacion_id == org),
            include_aliases=True,
        ),
    )


@event.listens_for(Session, "before_flush")
def _asignar_organizacion(session, contexto, instancias):
    org = session.info.get(CLAVE_ORGANIZACION)
    if org is None and session.info.get(CLAVE_SISTEMA, False):
        # Código de confianza (login, consola, tareas): asigna la
        # organización explícitamente; la base valida los NOT NULL.
        return

    for obj in session.new:
        if not isinstance(obj, (TenantMixin, TenantGlobalMixin)):
            continue
        if obj.organizacion_id is None:
            if org is not None:
                obj.organizacion_id = org
            else:
                raise ErrorOrganizacion(
                    f"No se puede crear {type(obj).__name__} sin organización"
                )
        elif org is not None and obj.organizacion_id != org:
            raise ErrorOrganizacion(
                f"{type(obj).__name__} pertenece a otra organización"
            )

    if org is None:
        return
    for obj in session.dirty:
        if isinstance(obj, (TenantMixin, TenantGlobalMixin)) and obj.organizacion_id != org:
            raise ErrorOrganizacion(
                f"No se puede modificar {type(obj).__name__} de otra organización"
            )

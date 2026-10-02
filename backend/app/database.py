"""
Conexión a PostgreSQL con SQLAlchemy: engine, sesiones y base declarativa.

El aislamiento entre organizaciones (tenants) vive en app/tenancy.py y se
engancha a estas sesiones con eventos: cada sesión sabe a qué organización
pertenece la petición y todo lo que consulta o inserta queda limitado a ella.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings


engine = create_engine(
    settings.database_url,
    # pool_pre_ping verifica que la conexión esté viva antes de usarla
    # (evita errores cuando la DB se reinicia o el pooler corta conexiones).
    pool_pre_ping=True,
    pool_size=settings.pool_size,
    max_overflow=settings.pool_max_overflow,
    # Recicla conexiones antes de que un pooler externo (Supabase, Neon) las
    # cierre por inactividad.
    pool_recycle=300,
    echo=settings.sql_echo,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """
    Dependencia de FastAPI: una sesión de base de datos por petición.

    La sesión nace SIN organización: hasta que la autenticación
    (app/security.py) fije una, las consultas a tablas de negocio no
    devuelven nada (falla cerrado). Los endpoints públicos que necesiten
    leer sin organización (login) lo declaran con tenancy.modo_sistema().
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

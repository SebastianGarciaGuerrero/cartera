"""
Modelo SQLAlchemy para 'empresa': los datos de la empresa que USA el sistema.

Tabla de una sola fila (id = 1). Es la pieza que hace al sistema white-label:
el membrete, la firma y el pie de página de los documentos Word salen de acá,
igual que el nombre que se muestra en la barra lateral. Cada instalación edita
esta fila desde Configuración → Mi empresa, sin tocar código.
"""

from sqlalchemy import Column, SmallInteger, String, Text, TIMESTAMP, text
from app.database import Base


class Empresa(Base):
    __tablename__ = "empresa"

    # Siempre 1: la tabla tiene un CHECK (id = 1) que garantiza la fila única.
    id = Column(SmallInteger, primary_key=True, server_default=text("1"))

    # Identidad legal
    razon_social = Column(String(200), nullable=False)
    nombre_fantasia = Column(String(100))
    rut = Column(String(12))

    # Membrete de los documentos
    wordmark = Column(String(100), nullable=False)
    bajada = Column(String(150))
    firma_documentos = Column(String(200))

    # Contacto (pie de las cartas)
    direccion = Column(String(200))
    ciudad = Column(String(100))
    horario_atencion = Column(String(120))
    telefonos = Column(String(120))
    emails = Column(String(200))
    sitio_web = Column(String(120))

    # Formas de pago del estado de cuenta (texto libre, una por línea)
    instrucciones_pago = Column(Text)

    updated_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"))

    def __repr__(self):
        return f"<Empresa(razon_social='{self.razon_social}')>"

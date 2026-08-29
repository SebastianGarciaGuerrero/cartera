"""
Cartera - Backend API
Punto de entrada principal de la aplicación FastAPI.
"""

import os
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db
from app.config import settings
# Modelos sin router propio todavía: se importan para registrar sus tablas en
# el metadata de SQLAlchemy, necesario para resolver las FK que apuntan a ellas
# (cobranzas.ejecutivo_id/paciente_id, gestiones/acuerdos.usuario_id).
from app.models import rol, usuario, paciente  # noqa: F401

# Auditoría automática: importar este módulo registra el listener que escribe
# en audit_log cada INSERT/UPDATE/DELETE de las tablas de negocio.
from app import auditoria  # noqa: F401

from app.routers import auth
from app.routers import empresa
from app.routers import usuarios
from app.routers import clientes
from app.routers import filiales
from app.routers import deudores
from app.routers import cobranzas
from app.routers import gestiones
from app.routers import acuerdos
from app.routers import pagos
from app.routers import judicial
from app.routers import exportar
from app.routers import documentos
from app.routers import importar
from app.routers import reportes
from app.routers import auditoria as auditoria_router


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Plataforma de gestión de cobranza extrajudicial y judicial"
)


# Registrar routers (módulos de endpoints)
app.include_router(auth.router)
app.include_router(usuarios.router)
app.include_router(empresa.router)
app.include_router(clientes.router)
app.include_router(filiales.router)
app.include_router(deudores.router)
app.include_router(cobranzas.router)
app.include_router(gestiones.router)
app.include_router(acuerdos.router)
app.include_router(pagos.router)
app.include_router(judicial.router)
app.include_router(exportar.router)
app.include_router(documentos.router)
app.include_router(importar.router)
app.include_router(reportes.router)
app.include_router(auditoria_router.router)


@app.get("/api/health")
def health_check():
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": "0.1.0",
        "environment": settings.environment
    }


@app.get("/api/health/db")
def health_check_db(db: Session = Depends(get_db)):
    try:
        resultado = db.execute(
            text("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")
        ).scalar()
        return {
            "status": "ok",
            "database": "PostgreSQL 16",
            "tablas_encontradas": resultado
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


# ============================================================
# Frontend compilado (producción)
# En desarrollo el frontend corre aparte con Vite (npm run dev).
# En producción se sirve la carpeta frontend/dist desde esta misma
# app: una sola URL para todo, sin CORS. El catch-all va AL FINAL
# para no pisar las rutas /api ni /docs.
# ============================================================

RUTA_DIST = Path(os.environ.get(
    "FRONTEND_DIST",
    str(Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"),
))

if RUTA_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=RUTA_DIST / "assets"), name="assets")

    @app.get("/{ruta:path}", include_in_schema=False)
    def servir_frontend(ruta: str):
        """Archivos del frontend; cualquier otra ruta cae en index.html (SPA)."""
        archivo = RUTA_DIST / ruta
        if ruta and archivo.is_file():
            return FileResponse(archivo)
        return FileResponse(RUTA_DIST / "index.html")
else:
    @app.get("/", include_in_schema=False)
    def root():
        return {
            "mensaje": "Cartera API funcionando correctamente",
            "documentacion": "/docs",
        }
"""
Cartera - Backend API
Punto de entrada principal de la aplicación FastAPI.
"""

import logging
import os
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.config import settings
from app.database import get_db
from app.tenancy import ErrorOrganizacion

# Registra todos los modelos en el metadata de SQLAlchemy (las relaciones y
# FK se resuelven por nombre de tabla).
import app.models  # noqa: F401

# Auditoría automática: importar este módulo registra el listener que escribe
# en audit_log cada INSERT/UPDATE/DELETE de las tablas de negocio.
from app import auditoria  # noqa: F401

from app.routers import auth
from app.routers import configuracion
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
from app.routers import agenda
from app.routers import calculadora
from app.routers import mensajes
from app.routers import panel
from app.routers import portal
from app.routers import estado_deudor


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("cartera")

VERSION = "0.2.0"

app = FastAPI(
    title=settings.app_name,
    version=VERSION,
    description="Plataforma de gestión de cobranza extrajudicial y judicial",
    # En producción no se publica el mapa de la API.
    docs_url=None if settings.es_produccion else "/docs",
    redoc_url=None,
    openapi_url=None if settings.es_produccion else "/openapi.json",
)

if settings.hosts_permitidos:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.hosts_permitidos)


# Política de contenido: solo recursos propios. 'unsafe-inline' en estilos
# porque React aplica estilos en línea; scripts sin excepciones. data: en
# imágenes por el QR del 2FA.
CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data: blob:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "object-src 'none'"
)


@app.middleware("http")
async def cabeceras_seguridad(request: Request, call_next):
    """ID de petición, log de acceso y cabeceras de seguridad en toda respuesta."""
    id_peticion = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    inicio = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - inicio) * 1000

    response.headers["X-Request-ID"] = id_peticion
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    if not request.url.path.startswith(("/docs", "/openapi.json")):
        response.headers["Content-Security-Policy"] = CSP
    if settings.es_produccion:
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    if request.url.path.startswith("/api/"):
        # Datos personales: que ningún proxy ni el navegador los guarde.
        response.headers.setdefault("Cache-Control", "no-store")

    if request.url.path.startswith("/api/"):
        log.info("%s %s %s %.0fms id=%s", request.method, request.url.path,
                 response.status_code, ms, id_peticion)
    return response


@app.exception_handler(ErrorOrganizacion)
async def _error_organizacion(request: Request, exc: ErrorOrganizacion):
    log.warning("Intento de acceso entre organizaciones: %s %s", request.url.path, exc)
    return JSONResponse(status_code=403, content={"detail": "Operación no permitida."})


@app.exception_handler(Exception)
async def _error_inesperado(request: Request, exc: Exception):
    # Nunca se devuelve el detalle interno (SQL, rutas, trazas) al cliente.
    log.exception("Error no controlado en %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Error interno. Si se repite, contacta a soporte."},
    )


# Registrar routers (módulos de endpoints)
app.include_router(auth.router)
app.include_router(configuracion.router)
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
app.include_router(agenda.router)
app.include_router(calculadora.router)
app.include_router(mensajes.router)
app.include_router(panel.router)
app.include_router(portal.router)
app.include_router(estado_deudor.equipo)
app.include_router(estado_deudor.publico)


@app.get("/api/health")
def health_check():
    return {"status": "ok", "version": VERSION}


@app.get("/api/health/db")
def health_check_db(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        log.exception("Health check de base de datos falló")
        raise HTTPException(status_code=503, detail="Base de datos no disponible")
    return {"status": "ok"}


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
)).resolve()

if RUTA_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=RUTA_DIST / "assets"), name="assets")

    @app.get("/{ruta:path}", include_in_schema=False)
    def servir_frontend(ruta: str):
        """Archivos del frontend; cualquier otra ruta cae en index.html (SPA)."""
        if ruta.startswith("api/"):
            raise HTTPException(status_code=404, detail="No encontrado")
        archivo = (RUTA_DIST / ruta).resolve()
        # Impide salir de la carpeta del frontend con rutas tipo ../../
        if ruta and archivo.is_file() and archivo.is_relative_to(RUTA_DIST):
            return FileResponse(archivo)
        return FileResponse(RUTA_DIST / "index.html")
else:
    @app.get("/", include_in_schema=False)
    def root():
        return {
            "mensaje": "Cartera API funcionando correctamente",
            "documentacion": "/docs",
        }

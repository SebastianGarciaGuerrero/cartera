# ============================================================
# Cartera — imagen de producción (backend + frontend juntos)
# Etapa 1: compila el frontend React con Node.
# Etapa 2: imagen Python con FastAPI sirviendo la API y el frontend.
# Al arrancar aplica las migraciones pendientes (alembic upgrade head,
# con candado: varias réplicas no migran a la vez).
# ============================================================

FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend .
RUN npm run build

FROM python:3.11-slim
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FRONTEND_DIST=/app/frontend/dist \
    ENVIRONMENT=production

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/migraciones ./migraciones
COPY backend/alembic.ini .
COPY --from=frontend /build/dist ./frontend/dist

# Nunca correr como root dentro del contenedor.
RUN useradd --create-home --uid 10001 cartera && chown -R cartera /app
USER cartera

# --proxy-headers: detrás del proxy del hosting, la IP real del cliente
# (para el límite de intentos y la bitácora de accesos) viene en
# X-Forwarded-For. Render, Railway y Hugging Face inyectan $PORT.
CMD ["sh", "-c", "if [ \"${RUN_MIGRATIONS:-1}\" = \"1\" ]; then alembic upgrade head; fi && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]

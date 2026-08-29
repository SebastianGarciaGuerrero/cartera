# ============================================================
# Cartera — imagen de producción (backend + frontend juntos)
# Etapa 1: compila el frontend React con Node.
# Etapa 2: imagen Python con FastAPI sirviendo la API y el frontend.
# ============================================================

FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend .
RUN npm run build

FROM python:3.11-slim
WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY --from=frontend /build/dist ./frontend/dist

ENV FRONTEND_DIST=/app/frontend/dist

# Render (y otros hosts) inyectan el puerto en $PORT.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

---
title: Cartera Demo
emoji: 📁
colorFrom: gray
colorTo: gray
sdk: docker
app_port: 8000
pinned: false
---

# Cartera

Plataforma SaaS de gestión de cobranza extrajudicial y judicial para
estudios jurídicos y empresas de cobranza. Reemplaza las planillas Excel de
gestión, recupero mensual y rendición al cliente por un sistema con base de
datos, historial inmutable y documentos automáticos.

Qué hace:

- **Cobranzas**: ficha por deuda con historial de gestiones, acuerdos de
  pago con cuotas generadas solas y registro de abonos con desglose.
- **Deudores y terceros**: ficha con contactos, avales, codeudores y todas sus
  deudas agrupadas.
- **Informes**: Excel de gestiones, recupero y rendición; Word de informe de
  gestiones y estado de cuenta.
- **Carga masiva**: alta de cobranzas y de gestiones desde Excel (las columnas
  se reconocen por título e incluyen los campos personalizados).
- **Cada estudio lo adapta solo**: campos personalizados (por estudio o por
  mandante), nombres en pantalla ("Mandante" en vez de "Cliente") y tipos de
  gestión propios, sin tocar código.
- **Administración**: usuarios con roles, invitación por correo, 2FA,
  auditoría de cambios y bitácora de accesos.

## Multi-organización (SaaS)

Cada estudio es una **organización**. Todos sus datos llevan
`organizacion_id` y el aislamiento entre estudios tiene dos capas
independientes:

1. **ORM** (`backend/app/tenancy.py`): toda consulta se filtra sola por la
   organización de la sesión y todo registro nuevo la recibe.
2. **PostgreSQL** (Row Level Security): en cada petición la app baja al rol
   `cartera_app`, que solo ve las filas de su organización, no puede borrar
   nada y no puede editar gestiones ni pagos. Las FK compuestas impiden
   enlazar registros de dos organizaciones distintas.

Planes (`backend/app/planes.py`): **base**, **profesional** y **premium**,
cada uno con sus funciones habilitadas.

## Seguridad

- Contraseñas con Argon2id; política de largo mínimo y contraseñas comunes.
- Access token de 15 minutos solo en memoria del navegador + sesión en cookie
  httpOnly/Secure/SameSite=Strict que se rota en cada uso (si un token robado
  se reutiliza, se cierra la sesión).
- Sesiones revocables al instante (logout, cambio de contraseña, desactivar
  usuario), bloqueo tras intentos fallidos, límite por IP.
- 2FA con app autenticadora + códigos de recuperación; semilla cifrada.
- Recuperación de contraseña e invitaciones por enlace de un solo uso.
- Bitácora de accesos y auditoría de cambios (Ley 21.719).
- Cabeceras de seguridad (CSP, HSTS, frame-ancestors), sin `/docs` en producción.

## Stack

- **Backend:** Python 3.11 + FastAPI + SQLAlchemy + Alembic
- **Frontend:** React 19 + TypeScript + Vite + TanStack Query
- **Base de datos:** PostgreSQL 16 (local en Docker, o Supabase / Neon)

## Estructura

```
├── docker-compose.yml       ← PostgreSQL para desarrollo local
├── backend/
│   ├── app/                 ← API FastAPI (models, schemas, routers)
│   ├── migraciones/         ← Alembic: el esquema versionado (0001, 0002...)
│   └── tests/               ← pytest contra PostgreSQL real
└── frontend/                ← SPA React
```

## Desarrollo local

Requisitos: Docker Desktop, Python 3.11 y Node 22.

```bash
docker compose up -d                       # PostgreSQL en el puerto 5433
cd backend
.venv\Scripts\activate
pip install -r requirements-dev.txt
alembic upgrade head                       # crea / actualiza el esquema
python -m app.cli crear-organizacion --nombre "Mi Estudio" --slug mi-estudio --admin-nombre "Tu Nombre" --admin-email tu@correo.cl --plan premium
uvicorn app.main:app --reload              # API en http://localhost:8000
```

El comando `crear-organizacion` imprime un enlace para elegir la contraseña del
administrador. En otra terminal:

```bash
npm run dev --prefix frontend              # http://localhost:5173
```

### Tests

```bash
cd backend
pytest
```

Usan un PostgreSQL real: el de `TEST_DATABASE_URL` si está definida, o uno
portátil que se levanta solo (`pgserver`, sin Docker).

### Migraciones

Todo cambio de esquema es una migración nueva en `backend/migraciones/versions/`
(`alembic revision -m "descripcion"`). Si crea una tabla de negocio, debe
llevar `organizacion_id` y llamar a `proteger_tabla_tenant()`; el test
`test_todas_las_tablas_con_organizacion_tienen_rls` falla si se olvida.

## Publicar

Ver `DEPLOY.md`.

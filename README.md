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

Plataforma de gestión de cobranza extrajudicial y judicial. Reemplaza las
planillas Excel de gestión, recupero mensual y rendición al cliente por un
sistema con base de datos, historial inmutable y documentos automáticos.

Qué hace:

- **Cobranzas** — ficha por deuda con historial de gestiones, acuerdos de
  pago con cuotas generadas automáticamente y registro de abonos con desglose.
- **Deudores** — ficha con contactos y todas sus deudas agrupadas.
- **Informes** — Excel de gestiones, recupero y rendición; Word de informe de
  gestiones y estado de cuenta.
- **Carga masiva** — alta de cobranzas y de gestiones desde una plantilla Excel.
- **Administración** — usuarios con roles, auditoría de cambios y datos de la
  empresa.

## White-label

El sistema no está atado a ninguna empresa. Hay dos lugares donde vive la
identidad, y ninguno exige tocar la lógica:

| Qué | Dónde | Quién lo cambia |
|---|---|---|
| Nombre del producto (login, pestaña) | `frontend/src/marca.ts` | quien instala |
| Razón social, membrete de los Word, dirección, fonos, formas de pago | tabla `empresa` → pantalla **Mi empresa** | el admin, desde la UI |

Los documentos Word toman el membrete, la firma y el pie de página de la tabla
`empresa`: cambiar de empresa es llenar un formulario, no editar código.

## Stack

- **Backend:** Python 3.11 + FastAPI + SQLAlchemy
- **Frontend:** React 19 + TypeScript + Vite + TanStack Query
- **Base de datos:** PostgreSQL 16
- **Contenedores:** Docker + Docker Compose

## Estructura del proyecto

```
├── .env                  ← Variables de entorno (NO subir a Git)
├── .env.example          ← Plantilla pública
├── docker-compose.yml    ← PostgreSQL para desarrollo local
├── database/
│   ├── init/             ← Se ejecuta al crear la base
│   │   ├── 001_schema.sql       ← DDL completo (17 tablas, 4 vistas)
│   │   └── 002_verificacion.sql ← Admin inicial y datos de ejemplo
│   └── migraciones/      ← Cambios sobre bases que ya existen
├── backend/              ← API FastAPI
└── frontend/             ← SPA React
```

## Setup inicial

### Requisitos
- Docker Desktop instalado y corriendo
- Python 3.11 y Node 20

### Levantar la base de datos
```bash
docker compose up -d
```

### Backend
```bash
cd backend
.venv\Scripts\activate
uvicorn app.main:app --reload
```

API en `http://localhost:8000`, docs interactivas en `/docs`.

### Frontend
```bash
npm run dev --prefix frontend
```

Sitio en `http://localhost:5173` (el proxy de Vite manda `/api` al backend).

### Primer ingreso
`admin@cartera.cl` / `cartera2026`. Cambiar la contraseña y llenar
**Administración → Mi empresa** antes de emitir documentos.

### Detener / reset
```bash
docker compose down       # detiene, conserva datos
docker compose down -v    # borra el volumen y todos los datos
```

## Conexión desde DBeaver

| Campo | Valor |
|---|---|
| Host | localhost |
| Port | 5433 |
| Database | cartera |
| Username | cartera_admin |
| Password | desarrollo_local_2026 |

## Publicar

Ver `DEPLOY.md`: demo estática sin servidor (Vercel) o instalación completa
con base de datos (Render + Neon).

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Cartera: plataforma de gestión de cobranza extrajudicial y judicial, pensada como producto white-label (se instala para cualquier empresa de cobranza). Reemplaza planillas Excel de gestión de cobranzas, recupero mensual y rendición al cliente. 17 tablas y 4 vistas SQL (`database/init/001_schema.sql`). Backend FastAPI completo (clientes, filiales, deudores, cobranzas, gestiones, acuerdos+cuotas, pagos, judicial, auth JWT con roles, auditoría, exportación Excel, documentos Word, carga masiva, reportes) y frontend React en `frontend/`. El módulo `pacientes` está diferido (en extrajudicial solo importa el deudor; `cobranzas.paciente_id` es nullable).

## Commands

Base de datos (PostgreSQL 16 en Docker, puerto 5433 para no chocar con un Postgres local en 5432):
```bash
docker compose up -d        # levantar (o doble click iniciar.bat)
docker compose down         # detener, conserva datos (o detener.bat)
docker compose down -v && docker compose up -d   # reset total, borra todo (o reset-total.bat)
docker compose logs -f postgres                  # logs (o verificar.bat)
docker exec -it cartera-postgres psql -U cartera_admin -d cartera   # consola SQL (o consola-sql.bat)
```
El DDL en `database/init/*.sql` se ejecuta automáticamente solo la primera vez que se crea el volumen (orden alfabético).

Backend (Python 3.11 venv en `backend/.venv`):
```bash
cd backend
.venv\Scripts\activate
uvicorn app.main:app --reload
```
API en `http://localhost:8000`, docs interactivas en `/docs`. Variables de entorno en `backend/.env` (DATABASE_URL apunta a `localhost:5433`).

No hay tests ni linter configurados todavía.

## Architecture

FastAPI con capas separadas por módulo de dominio (`backend/app/{models,schemas,routers}/<entidad>.py`):

- **models/** — clases SQLAlchemy mapeadas 1:1 a las tablas de `database/init/001_schema.sql`. `Base` y el engine viven en `app/database.py`; `get_db()` es la dependencia de sesión por request.
- **schemas/** — Pydantic, separados de los modelos. Convención: `<Entidad>Base` (campos editables compartidos) → `<Entidad>Create` (hereda Base) → `<Entidad>Update` (todos los campos opcionales, para PUT parcial con `exclude_unset=True`) → `<Entidad>Response` (agrega id/timestamps, `model_config = ConfigDict(from_attributes=True)`). Variantes enriquecidas (ej. `FilialConCliente`) heredan de `Response` y agregan campos de tablas relacionadas resueltos a mano en el router.
- **routers/** — un `APIRouter` por entidad con `prefix="/api/<entidad>"`, registrado en `app/main.py` vía `app.include_router(...)`. CRUD estándar: GET lista (con `skip`/`limit`/filtro `solo_activos`), GET por id, POST (captura `IntegrityError` → 400 si viola UNIQUE), PUT (parcial), DELETE (soft delete, ver regla abajo). 404 explícito cuando el recurso no existe.
- **config.py** — `Settings` (pydantic-settings) lee `backend/.env`.

### Patrón para agregar un módulo nuevo
Usar `cliente`/`filial` como referencia exacta: crear `models/<entidad>.py`, `schemas/<entidad>.py`, `routers/<entidad>.py` siguiendo la misma estructura de clases y endpoints, y registrar el router en `main.py`. Las relaciones FK se definen en el modelo con `relationship(..., backref=...)` (ver `Filial.cliente`); el router valida que la entidad referenciada exista (404) antes de insertar.

## Reglas de negocio (no negociables)

Definidas como convención explícita en el encabezado de `database/init/001_schema.sql`:

- **Nunca DELETE físico.** Todo borrado es soft delete vía columna `activo BOOLEAN`. Los endpoints DELETE solo hacen `entidad.activo = False; db.commit()` (ver `desactivar_cliente`/`desactivar_filial`). Esto preserva el historial de cobranzas vinculadas.
- **Gestiones son inmutables.** La tabla `gestiones` no tiene `updated_at` y no debe tener endpoint PUT/DELETE. Un error se corrige agregando una gestión nueva, nunca editando la existente — protege la integridad del historial legal. `pagos` y `acuerdos_pago` siguen el mismo principio (sin `updated_at`; una renegociación crea un acuerdo nuevo en vez de editar el vigente).
- **RUT chileno como identificador natural.** Formato `'12345678-9'`, `VARCHAR(12)`, `UNIQUE` en `clientes`, `deudores` y `pacientes`. En `ClienteUpdate` el campo `rut` se omite a propósito (no se puede cambiar una vez creado).
- **Montos siempre `NUMERIC(15,2)`, nunca FLOAT** (evita errores de redondeo en dinero).
- **`cobranzas.numero`** es `GENERATED ALWAYS AS IDENTITY` — número de cobranza único global, nunca se inserta manualmente.
- **Nada de marca en el código.** El nombre del producto vive en `frontend/src/marca.ts`; los datos de la empresa que usa el sistema (razón social, membrete de los Word, dirección, fonos, formas de pago) viven en la tabla `empresa` (fila única) y se editan desde la pantalla Mi empresa. No hardcodear nombres, direcciones ni teléfonos en routers ni componentes.
- **`audit_log`** es solo-INSERT (cumplimiento Ley 21.719 de protección de datos), pensado para implementarse con triggers en tablas críticas — todavía no implementado en el backend.

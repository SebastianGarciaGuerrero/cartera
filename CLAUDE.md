# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Cartera: plataforma SaaS multi-organización de gestión de cobranza extrajudicial y judicial para estudios jurídicos y empresas de cobranza. Cada estudio es una `organizacion` (tenant) con su plan (`base` / `profesional` / `premium`, ver `backend/app/planes.py`). Backend FastAPI + SQLAlchemy + Alembic, frontend React 19 + TS + Vite + TanStack Query, PostgreSQL 16 (local en Docker o Supabase). Hoja de ruta en `docs/ROADMAP.md`.

## Commands

```bash
docker compose up -d                 # Postgres local en el puerto 5433 (o iniciar.bat)
cd backend && .venv\Scripts\activate
alembic upgrade head                 # aplica migraciones (backend/migraciones)
alembic revision -m "descripcion"    # migración nueva (se escribe a mano, sin autogenerate)
python -m app.cli crear-organizacion --nombre ... --slug ... --admin-nombre ... --admin-email ... [--plan premium]
python -m app.cli -h                 # listar-organizaciones, cambiar-plan, cambiar-estado, enlace-acceso
uvicorn app.main:app --reload        # API en :8000, /docs solo fuera de producción
pytest                               # tests contra Postgres real (TEST_DATABASE_URL o pgserver portátil)
npm run dev --prefix frontend        # :5173, proxy /api → :8000
npm run build --prefix frontend      # tsc -b + vite build
npm run lint --prefix frontend       # oxlint
npm run dev:demo --prefix frontend   # demo sin backend (src/api/demo.ts simula la API en el navegador)
```

Configuración en `backend/.env` (plantilla: `backend/.env.example`). En `production`/`demo` la app no arranca sin `SECRET_KEY` fuerte.

## Architecture

FastAPI con capas por dominio: `backend/app/{models,schemas,routers}/<entidad>.py`, routers registrados en `app/main.py`. Convención de schemas: `<Entidad>Base` → `Create` → `Update` (todo opcional, `exclude_unset=True`) → `Response` (`from_attributes=True`).

### Multi-organización (lo más importante)

- Todo modelo de negocio hereda `TenantMixin` (`app/tenancy.py`). Catálogos mixtos (filas de sistema con `organizacion_id NULL` + propias) usan `TenantGlobalMixin` (ej. `TipoGestion`).
- **Capa ORM**: un evento `do_orm_execute` agrega `organizacion_id = <org de la sesión>` a toda consulta y `before_flush` asigna la organización a todo objeto nuevo. Los routers NO filtran por organización a mano; usar `db.get(Modelo, id)` y dejar que un id ajeno dé 404.
- **Capa base de datos (RLS)**: `get_current_user` (`app/security.py`) llama a `activar_organizacion(db, org)`, que hace `SET LOCAL ROLE cartera_app` + `set_config('app.organizacion_id', ...)` en cada transacción. `cartera_app` no tiene DELETE en ninguna tabla ni UPDATE en `gestiones`/`pagos`/`audit_log`.
- Sesión sin organización ni modo sistema = ve tablas vacías y no puede insertar (falla cerrado). `modo_sistema(db)` / `sesion_sistema()` solo para login, validación de token, tablas internas (`sesiones`, `tokens_un_uso`) y CLI/tareas.
- SQL crudo (vistas en `exportar.py`): filtrar igual por `organizacion_id = :org` (doble capa).
- FKs compuestas `(organizacion_id, x_id)` en la base: una fila no puede apuntar a otra organización.

### Migraciones (Alembic, escritas a mano)

- `backend/migraciones/versions/000N_*.py`. 0001 crea el esquema base (o adopta una base vieja), 0002 multi-organización, 0003 generalización (terceros, campos personalizados), 0004 seguridad, 0005 RLS.
- **Tabla de negocio nueva** → columna `organizacion_id UUID NOT NULL REFERENCES organizaciones(id)`, FKs compuestas a sus padres, y `proteger_tabla_tenant("tabla")` de `migraciones/utilidades.py`. El test `test_todas_las_tablas_con_organizacion_tienen_rls` falla si falta.
- Vistas con `WITH (security_invoker = true)` y columna `organizacion_id`; dar `GRANT SELECT` a `cartera_app`.
- `alembic.ini` debe quedar en ASCII (Alembic lo lee con la codificación de Windows).

### Seguridad

- Login (`routers/auth.py`): JSON `{email, password}` → access token JWT (15 min, `sid` de la sesión) + refresh opaco en cookie `cartera_refresh` (httpOnly, SameSite=Strict, path `/api/auth`), rotado en cada `/auth/refresh` con detección de reutilización. Los endpoints con cookie exigen la cabecera `X-Requested-With: cartera`.
- `get_current_user` valida que la sesión siga viva en la base en cada petición (logout/cambio de clave cortan al instante).
- Contraseñas Argon2id (`validar_password`: mín. 12, no comunes); bcrypt heredado se re-hashea al entrar. 2FA TOTP (`app/mfa.py`), semilla cifrada con Fernet.
- Dependencias de autorización: `usuario_autorizado` (usuarios internos; `viewer` solo lectura; `mandante` excluido), `require_admin`, `requiere_roles(...)`, `requiere_funcion("judicial")` (plan).
- Frontend: el access token vive solo en memoria (`api/client.ts`); al cargar se pide con `/auth/refresh`. Nunca guardar tokens en localStorage.

### Agenda y calculadora (Fase 2)

- `app/agenda.py` arma la agenda desde los datos: última gestión con `fecha_proximo_contacto` (promesa si el tipo es `promesa_pago`), cuotas abiertas de acuerdos vigentes y `recordatorios`. Fechas de negocio en hora de Chile (`app/indicadores.hoy_chile()`); en el frontend usar `fechaLocal()`/`fechaLegible()` de `componentes/utiles.tsx`, nunca `toISOString()` para fechas.
- `app/calculos.py`: honorarios 3-6-9 / judicial, abono → capital, plan de cuotas. Decimal y redondeo tipo `Math.round` (verificado contra la calculadora `cobra369`). El servidor es la única fuente de verdad; `frontend/src/api/demoCalculos.ts` es solo para la demo.
- UF: `app/indicadores.py` (mindicador.cl → boostr.cl) con caché en la tabla `indicadores`.

### Portal de mandantes

- Rol `mandante` + `usuarios.cliente_id`: no entra a la API interna (`ROLES_INTERNOS` en `security.py`), solo a `routers/portal.py`, que filtra todo por su cliente. Función de plan `portal_mandantes`.
- Frontend: `componentes/PortalLayout.tsx` (menú propio, rutas `/portal/*`) y `paginas/Portal.tsx`. `Layout` redirige al mandante a `/portal` y `PortalLayout` devuelve a `/` a los usuarios internos.

### Personalización por organización

- Campos personalizados (`campos_personalizados`, `app/campos.py`): valores en `datos_extra` JSONB de cobranzas/deudores, validados contra la definición. Pueden limitarse a un mandante (`cliente_id`).
- Etiquetas de la UI en `organizaciones.configuracion["etiquetas"]` (claves en `routers/configuracion.py: ETIQUETAS_DEFECTO`); el frontend usa `useAuth().etiqueta(clave, defecto)`.
- Tipos de gestión de sistema tienen `codigo` estable; el código usa `tipo_de_sistema(db, "abono")`, nunca el nombre.

## Reglas de negocio (no negociables)

- **Nunca DELETE físico.** Soft delete con `activo`. La base lo impone (sin permiso DELETE para `cartera_app`).
- **Gestiones, pagos, audit_log y eventos_acceso son inmutables** (trigger en la base). Un error se corrige con un registro nuevo. Acuerdos: solo cambia estado/firma; renegociar = acuerdo nuevo.
- **RUT**: se valida (módulo 11) y se guarda normalizado `12345678-5` (`app/rut.py`, tipo `Rut` en schemas de entrada). Único por organización.
- **Montos `NUMERIC(15,2)`**, nunca FLOAT. Solo el **capital** descuenta el saldo de la cobranza.
- **`cobranzas.numero`**: correlativo por organización asignado por trigger (`organizaciones.numero_cobranza_siguiente`); no cambia nunca.
- **Nada de marca ni de rubro en el código**: nombre del producto en `frontend/src/marca.ts`; datos del estudio en `empresa` (una fila por organización); lo propio de un rubro va en campos personalizados.
- **Auditoría automática** (`app/auditoria.py`, listener `after_flush`) con `organizacion_id`; no auditar a mano. No copia el alta de `gestiones` ni `pagos` (inmutables): medido, la copia pesaba más que el dato.
- El modo demo (`frontend/src/api/demo.ts`) replica la API: al cambiar un endpoint usado por el frontend, actualizarlo también.

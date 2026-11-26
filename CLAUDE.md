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
python -m app.cli simular --anios 5 --password ...   # SOLO base de prueba: org "simulacion" con 5 años de cartera
python -m app.cli medir-rendimiento --password ...   # tiempos de las pantallas principales con esa cartera
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

### Portal del deudor

- `routers/estado_deudor.py`: el equipo genera un enlace (`enlaces_deudor`, solo el hash del token) y el deudor lo abre en `/estado#t=TOKEN` (fragmento: no llega al servidor ni a los logs) escribiendo su RUT. `POST /api/publico/estado` busca el enlace en modo sistema y después lee todo con `activar_organizacion` (RLS). Nunca devolver gestiones, honorarios, usuarios ni estados internos (`archivada`, `castigo`).
- Frontend: `paginas/EstadoDeudor.tsx` (pública, fuera de los layouts, trato de "usted") y `componentes/EnlaceDeudor.tsx` (modal en la ficha de la cobranza).

### Ciclo de vida y módulo judicial (Fase 3)

- `cobranzas.etapa` (ingreso / extrajudicial / para_demanda / judicial) la mueven `app/ciclo.py` y dos triggers (migración 0010): la primera gestión pasa de ingreso a extrajudicial, y de judicial no se vuelve (la base lo rechaza). Cada cambio queda en `cambios_etapa`; quién y por qué llegan por `set_config('app.usuario_id' / 'app.motivo_etapa')` → usar `ciclo.fijar_contexto`. El término no es etapa: sale de `estado` + `motivo_cierre` / `fecha_cierre`.
- `app/judicial.py`: `crear_causa` (una causa = un rol; varias cobranzas del mismo deudor y cliente vía `causa_cobranzas`), `registrar_tramite` (plazo = el del tipo salvo uno a mano; la etapa procesal sigue al tipo), `terminar_causa`. El plazo pendiente de una causa es el del ÚLTIMO trámite con tipo por fecha (las observaciones no lo cumplen). `tramites` y `cambios_etapa` son inmutables (trigger), como `gestiones`.
- Catálogos mixtos `tipos_tramite` y `tribunales` (sistema + propios); los de sistema se siembran desde `migraciones/datos_judicial.py` y no se editan por API.
- Gastos: por_rendir → rendido (en una `rendiciones_gastos`) → reembolsado. Routers `judicial.py` y `gastos.py` exigen la función de plan `judicial`; el ciclo de vida (`/api/cobranzas/{id}/ciclo`) es para todos.
- Frontend: `componentes/CicloVida.tsx` (barra en la ficha), `paginas/Judicial.tsx` (bandeja), `paginas/Causa.tsx`, `paginas/Gastos.tsx`. En la demo solo existe la barra (lectura).

### Personalización por organización

- Campos personalizados (`campos_personalizados`, `app/campos.py`): valores en `datos_extra` JSONB de cobranzas/deudores, validados contra la definición. Pueden limitarse a un mandante (`cliente_id`).
- Etiquetas de la UI en `organizaciones.configuracion["etiquetas"]` (claves en `routers/configuracion.py: ETIQUETAS_DEFECTO`); el frontend usa `useAuth().etiqueta(clave, defecto)`.
- Tipos de gestión de sistema tienen `codigo` estable; el código usa `tipo_de_sistema(db, "abono")`, nunca el nombre.

### Operación con cartera real (migración 0015)

- **Carga masiva** (`app/carga_masiva.py`, endpoints en `routers/importar.py`): reconoce títulos con sinónimos (`COLUMNAS_COBRANZA`, `CAMPOS_PERSONA`; "Rut Paciente" → tercero con rol), detecta la fila de títulos y carga varias hojas; un teléfono con formato de fecha se lee como número (parche de `openpyxl.worksheet._reader.from_excel`). Corre en segundo plano (`app/trabajos.py`, tabla `trabajos`): el endpoint responde 202 con `trabajo_id` y se consulta `GET /api/importar/trabajos/{id}`. En los tests el `TestClient` ya la deja terminada. Modo `actualizar` solo admin; dentro de un archivo manda la primera fila de cada deudor.
- **ID cliente único por (cliente, filial)**: índice parcial `NULLS NOT DISTINCT` (no `UniqueConstraint` en el modelo).
- **Estado `eliminada`** (eliminada de cartera, motivo `eliminada_cartera`): terminal, en `ciclo.ESTADOS_TERMINALES`; no cuenta como asignado en panel/portal. Masivo en `routers/cartera.py` (también asignar/repartir), permiso `cartera_gestionar`.
- **Pagos anulados**: `operaciones.anular_pago` revierte la cascada; la base solo permite poner `anulado_at/anulado_por/motivo_anulacion` una vez (trigger `pagos_solo_anulacion`). Todo total de pagos filtra `anulado_at IS NULL` (vistas `vista_recupero`/`vista_rendicion` incluidas). Permiso `pagos_anular`.
- **Agenda**: ítems con `seccion` (llamadas, whatsapp, correos, cuotas_vencidas, bajas…); tipo `baja` = acuerdo vigente sin pagos de cuota en `MESES_SIN_PAGO_BAJA` (3) meses → `POST /api/acuerdos/{id}/baja`. Recordatorios con `tipo`.
- **Pasar a producción** (`app/produccion.py`, `/api/organizacion/produccion`): única vez, borra la cartera de prueba de la organización con los triggers de inmutabilidad apagados SOLO en esa transacción y fija `numero_cobranza_siguiente`.

### Interfaz por rol: menú y ficha de la cobranza

- **Menú** (`componentes/MenuLateral.tsx`): por áreas (Extrajudicial, Judicial, Ingresos y cargas, Reportes, Administración) y según el rol; abogado/procurador ven primero lo judicial. Grupos plegables recordados por persona en `localStorage` (`cartera.menu.<usuarioId>`). `useVeJudicial()` decide si alguien trabaja lo judicial.
- **Ficha de la cobranza** (`paginas/CobranzaDetalle.tsx`): cabecera fija (deudor, cliente, ejecutivo, contacto, `CicloVida` compacto y `ResumenDeuda`) y pestañas Gestiones · Acuerdo y pagos · Datos del caso · Documentos · Judicial. La pestaña va en la URL (`?ver=pagos|judicial|…`); avisos, agenda y seguimiento enlazan directo a la que corresponde. Abogado/procurador abren en Judicial.
- **Un solo camino para pagar**: "Registrar pago" (cabecera) y "Pagar" en una cuota abren el mismo formulario de `RegistrarGestion` (modo pago, con la cuota elegida); `Finanzas` ya no registra pagos por su cuenta. La lista de pagos con anulación es `ListaPagos` (`HistorialPagos.tsx`).
- **Tipos de gestión**: `GET /api/gestiones/tipos` trae `usos` (gestiones de quien consulta en 90 días, sin las masivas); el formulario muestra los 5 más usados y "Más…".

## Reglas de negocio (no negociables)

- **Nunca DELETE físico.** Soft delete con `activo`. La base lo impone (sin permiso DELETE para `cartera_app`).
- **Gestiones, pagos, audit_log y eventos_acceso son inmutables** (trigger en la base). Un error se corrige con un registro nuevo. Acuerdos: solo cambia estado/firma; renegociar = acuerdo nuevo.
- **RUT**: se valida (módulo 11) y se guarda normalizado `12345678-5` (`app/rut.py`, tipo `Rut` en schemas de entrada). Único por organización.
- **Montos `NUMERIC(15,2)`**, nunca FLOAT. Solo el **capital** descuenta el saldo de la cobranza.
- **`cobranzas.numero`**: correlativo por organización asignado por trigger (`organizaciones.numero_cobranza_siguiente`); no cambia nunca.
- **Nada de marca ni de rubro en el código**: nombre del producto en `frontend/src/marca.ts`; datos del estudio en `empresa` (una fila por organización); lo propio de un rubro va en campos personalizados.
- **Auditoría automática** (`app/auditoria.py`, listener `after_flush`) con `organizacion_id`; no auditar a mano. No copia el alta de `gestiones` ni `pagos` (inmutables): medido, la copia pesaba más que el dato.
- El modo demo (`frontend/src/api/demo.ts`) replica la API: al cambiar un endpoint usado por el frontend, actualizarlo también.

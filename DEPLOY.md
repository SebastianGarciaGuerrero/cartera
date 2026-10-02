# Cómo publicar Cartera

Arquitectura: **una sola URL**. El backend FastAPI sirve también el frontend
compilado (imagen Docker única). Al arrancar, la imagen aplica las
migraciones pendientes (`alembic upgrade head`).

## Opción rápida: demo solo-frontend en Vercel (sin backend)

Para **mostrar** el sistema con datos simulados que viven en el navegador de
quien mira. Gratis y sin base de datos.

1. En https://vercel.com → **Add New → Project** → importar el repo `cartera`.
2. **Root Directory**: `frontend` (el `frontend/vercel.json` ya trae
   `npm run build:demo` y las rewrites del SPA).
3. Deploy. Se entra con `admin@demo.cl` / `demo1234`.

No funcionan en la demo: descargas Excel/Word, carga masiva ni correos.

---

## Versión completa (servidor + base de datos real)

### Paso 1: base de datos en Supabase

1. En el proyecto de Supabase: **Connect** (arriba) → pestaña **Connection
   string** → **Session pooler**. Copiar la URL:
   ```
   postgresql://postgres.<ref>:[YOUR-PASSWORD]@aws-0-<region>.pooler.supabase.com:5432/postgres
   ```
   y reemplazar `[YOUR-PASSWORD]` por la contraseña de la base (Project
   Settings → Database → *Reset database password* si no la tienes).
   ⚠️ No usar la "Direct connection" (`db.<ref>.supabase.co`): es solo IPv6 y
   falla desde Windows y desde la mayoría de los hostings.
2. La URL pública (`https://<ref>.supabase.co`) y la *publishable key* **no
   se usan**: la app habla directo con PostgreSQL. Las migraciones dejan a los
   roles `anon`/`authenticated` (los de esa API pública) sin ningún permiso y
   todas las tablas con RLS, así que esa clave no expone datos.
3. Ponerla en `backend/.env` como `DATABASE_URL=...` (ese archivo no se sube
   a Git).

### Paso 2: crear el esquema y la primera organización

Desde tu PC, en `backend` con el venv activo:

```powershell
alembic upgrade head
python -m app.cli crear-organizacion --nombre "Mi Estudio" --slug mi-estudio --admin-nombre "Tu Nombre" --admin-email tu@correo.cl --plan premium
```

El segundo comando imprime un enlace para que el administrador elija su
contraseña. Después, en la app: **Administración → Mi empresa** (membrete de
los documentos) y **Configuración** (campos y nombres propios).

Otros comandos de plataforma: `listar-organizaciones`, `cambiar-plan`,
`cambiar-estado` (suspender), `enlace-acceso` (`python -m app.cli -h`).

### Paso 3: la aplicación

Cualquier hosting que corra el `Dockerfile` sirve (Railway, Render, Fly.io,
Hugging Face Spaces, un VPS). Variables de entorno **obligatorias**:

| Variable | Valor |
|---|---|
| `DATABASE_URL` | la del Session pooler de Supabase |
| `SECRET_KEY` | aleatoria, 48+ caracteres: `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `ENVIRONMENT` | `production` |
| `URL_PUBLICA` | la URL donde queda publicada (ej. `https://app.tudominio.cl`) |
| `HOSTS_PERMITIDOS` | el dominio, sin https (ej. `app.tudominio.cl`) |

Recomendadas: `CLAVE_CIFRADO` (cifra las semillas 2FA; ver `backend/.env.example`)
y el correo `SMTP_*` (sin eso no salen las invitaciones ni la recuperación de
contraseña). Con Google Workspace: `SMTP_HOST=smtp.gmail.com`,
`SMTP_PUERTO=587`, la casilla como usuario y una **contraseña de aplicación**.

La app **no arranca** en producción si `SECRET_KEY` falta o es débil: así
no queda expuesta por un descuido.

### Antes de cargar datos reales de deudores

- Plan de Supabase con **backups diarios** (el gratuito no tiene restauración
  y pausa el proyecto tras una semana sin uso).
- Dominio propio con HTTPS.
- 2FA activado en las cuentas de administrador.
- Revisar con un abogado los textos legales (Ley 21.719: aviso de privacidad
  y contrato de encargo de tratamiento con cada estudio).

## Si algo falla

- **"SECRET_KEY insegura"** al arrancar: falta la variable o es corta.
- **El login falla con "Sesión vencida" al recargar**: el sitio debe servirse
  por HTTPS (la cookie de sesión es `Secure`).
- **Error de conexión a la base**: revisa que la URL sea la del *pooler* y
  que la contraseña no tenga caracteres sin codificar (`@`, `#`, `/` → usar
  `%40`, `%23`, `%2F`).
- `GET /api/health/db` dice si la app llega a la base.

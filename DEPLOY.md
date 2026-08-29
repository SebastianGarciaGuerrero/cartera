# Cómo publicar Cartera

Arquitectura: **una sola URL** — el backend FastAPI sirve también el frontend
compilado (por eso no usamos Vercel: acá hay Python + PostgreSQL, no solo
archivos estáticos).

## ⭐ Opción rápida: DEMO solo-frontend en Vercel (sin backend)

Para **mostrar** el sistema (interfaz + flujo completo con datos simulados
que viven en el navegador de quien mira). No necesita base de datos ni
servidor: gratis para siempre en Vercel y el código queda privado.

1. En https://vercel.com → **Add New → Project** → importar el repo `cartera`.
2. En la configuración del proyecto:
   - **Root Directory**: `frontend`
   - Framework: Vite (lo detecta solo; el `frontend/vercel.json` ya trae el
     build command `npm run build:demo` y las rewrites del SPA)
3. Deploy → sale una URL tipo `https://cartera.vercel.app`.
4. Se entra con `admin@demo.cl` / `demo1234` (la pantalla de login lo indica).

Qué funciona en la demo: login, cobranzas, deudores, ficha completa,
registrar gestiones, acuerdos con cuotas, abonos con desglose y cascada,
reportes de equipo. Los datos se guardan en el navegador de cada visitante.
Qué NO funciona: descargas Excel/Word y carga masiva (muestran un aviso;
requieren el servidor).

---

## Versión completa (con servidor y base de datos real)

La base de datos va SIEMPRE en **Neon** (Paso 1 y 2). Para la aplicación hay
tres opciones — elige la primera que tengas disponible:

| Opción | Costo | Nota |
|---|---|---|
| A. Hugging Face Spaces | Gratis para siempre, sin tarjeta | El código del Space queda visible públicamente |
| B. Railway | Crédito de prueba (~US$5, dura ~1 mes) | Solo si nunca la usaste |
| C. Render | Plan free | Solo si tu cuenta lo permite |

## Paso 1 — Base de datos en Neon (5 min)

1. Crear cuenta en https://neon.tech (con Google o GitHub).
2. Crear un proyecto (nombre: `cartera`, región: São Paulo o US East).
3. Copiar la **connection string** que te muestra (algo como
   `postgresql://usuario:clave@ep-xxxx.aws.neon.tech/neondb?sslmode=require`).

## Paso 2 — Cargar el esquema y los datos de práctica (2 min)

Desde tu PC, en la carpeta `backend` con el venv activo:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python scripts/init_db_produccion.py "postgresql://...la URL de Neon..."
```

Eso crea las 17 tablas, las vistas, un cliente de ejemplo y el usuario
administrador:

| Email | Contraseña | Rol |
|---|---|---|
| admin@cartera.cl | cartera2026 | admin |

Cambiar esa contraseña en el primer ingreso, y llenar
**Administración → Mi empresa** (razón social, membrete, fonos): de ahí salen
los datos de todos los documentos Word. Para crear más cuentas de entrada,
editar la lista `USUARIOS_EXTRA` de `scripts/init_db_produccion.py` antes de
correrlo, o crearlas después desde Administración → Usuarios.

## Paso 3, opción A — Hugging Face Spaces (gratis, sin tarjeta)

1. Crear cuenta en https://huggingface.co (gratis, sin tarjeta).
2. Arriba a la derecha: **New → Space**. Nombre: `cartera-demo`,
   License: ninguna, SDK: **Docker** (plantilla Blank), visibilidad
   **Public** (un Space privado no lo puede abrir quien no tenga cuenta).
3. En el Space: **Settings → Variables and secrets** → agregar dos *Secrets*:
   - `DATABASE_URL` = la URL de Neon del Paso 1
   - `SECRET_KEY` = cualquier texto largo aleatorio (ej. 40 letras al azar)
4. Desde tu PC, en la carpeta del proyecto, subir el código al Space:
   ```powershell
   git remote add hf https://huggingface.co/spaces/TU_USUARIO/cartera-demo
   git push hf main
   ```
   (te pedirá usuario y un token de HF: se crea en Settings → Access Tokens,
   tipo Write). El README del repo ya trae los metadatos que el Space necesita.
5. El Space compila la imagen (unos minutos) y queda en
   `https://TU_USUARIO-cartera-demo.hf.space` — esa es la URL que compartes.
6. Para actualizar la demo: `git push hf main` después de cada cambio.

> ⚠️ El código del Space público es visible para cualquiera. No hay
> credenciales en el código (van en Secrets), y los datos son de práctica,
> así que para una demo está bien. Para producción real: VPS propio con HTTPS.

## Paso 3, opción B — Railway (si nunca la usaste)

1. Crear cuenta en https://railway.app (entrar con GitHub). El plan de prueba
   regala ~US$5 de crédito.
2. **New Project → Deploy from GitHub repo** → elegir `cartera`.
   Railway detecta el `Dockerfile` solo.
3. En el servicio → **Variables**: agregar `DATABASE_URL` (la URL de Neon)
   y `SECRET_KEY` (texto largo aleatorio).
4. **Settings → Networking → Generate Domain** para obtener la URL pública.
5. Cada `git push` a `main` redespliega solo.

## Paso 3, opción C — Render

1. https://render.com → **New → Blueprint** → repo `cartera` (lee el
   `render.yaml` del repo). Pegar `DATABASE_URL` cuando lo pida. Deploy.
2. El plan free "duerme" tras ~15 min sin visitas (despierta en ~1 min).

## Si algo falla

- **La página carga pero el login falla** → revisa que `DATABASE_URL` esté
  bien pegada en Render (Environment) y que el Paso 2 se haya ejecutado.
- **"Application failed to respond"** → mira los Logs del servicio en Render.
- La API interactiva queda en `https://tu-url.onrender.com/docs`.

## Importante

- Los datos de la demo son de práctica (ficticios). **No cargar datos
  reales de deudores en la demo pública** — eso queda para el despliegue
  definitivo (VPS con HTTPS propio).
- Las contraseñas de demo son débiles a propósito; en producción real se
  cambian.

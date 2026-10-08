# Logos de las empresas

Cartera no trae el logo de ningún estudio. Cada empresa que usa la plataforma
manda el suyo, y aparece en el membrete de los documentos Word (acuerdos,
informes, estados de cuenta) y en la barra lateral. Mientras no tenga, los
documentos muestran un recuadro gris **"LOGO DE LA EMPRESA"** donde irá.

## Qué pedirle a la empresa

- Formato **PNG** (ideal, con fondo transparente) o **JPG**.
- Ancho de al menos **600 px**, ojalá horizontal (más ancho que alto).
- Peso de hasta **1 MB**.
- No SVG: por seguridad no se aceptan.

## Cómo cargarlo

1. Guarda el archivo en esta carpeta con el *slug* de la organización:
   `logos/<slug>.png`. Las imágenes **no se suben a GitHub** (están en
   `.gitignore`): el repositorio es público y los logos son de los clientes.
2. Cárgalo en la plataforma, de una de estas dos formas:
   - El administrador de la empresa: **Administración → Mi empresa → Logo**.
   - Tú, por consola (desde `backend`, con el venv activo):
     ```
     python -m app.cli subir-logo --slug <slug> --archivo ../logos/<slug>.png
     ```
3. Anótalo en la tabla de abajo.

## Registro

| Empresa | Slug | Archivo | Recibido | Cargado | Notas |
|---|---|---|---|---|---|
| _(ejemplo)_ Estudio Ejemplo SpA | `estudio-ejemplo` | `logos/estudio-ejemplo.png` | 2026-10-07 | 2026-10-07 | PNG 1200×400 |

# Hoja de ruta: Cartera como producto SaaS

## Fase 1: cimientos ✅ (rama `saas/fase-1`)

- Migraciones versionadas con Alembic; la base existente se adopta sin pérdida.
- Multi-organización con aislamiento en dos capas (ORM + RLS de PostgreSQL),
  FKs compuestas, N° de cobranza correlativo por organización.
- Seguridad: Argon2id, tokens cortos + refresh rotativo en cookie httpOnly,
  sesiones revocables, bloqueo por intentos, 2FA, recuperación e invitaciones
  por correo, bitácora de accesos, cabeceras de seguridad, inmutabilidad en BD.
- Generalización: nombres neutros, terceros (aval/codeudor/paciente), campos
  personalizados por organización y por mandante, etiquetas propias, tipos de
  gestión propios, validación de RUT.
- Planes base / profesional / premium con funciones habilitables.
- CLI de plataforma, 30 tests contra Postgres real, CI con auditoría de dependencias.

## Fase 2: trabajo diario del estudio ✅

Hecho: agenda con calendario y atrasados, recordatorios, correo diario con la agenda
(`python -m app.cli enviar-agenda`), calculadora 3-6-9 con acuerdos/avenimientos asistidos
(cuotas con desglose que se usa al pagar), UF del día con caché, mensaje de pago listo para
WhatsApp/correo, pantalla de clientes con datos de transferencia propios.
Pendiente de esta fase: documento Word del acuerdo con el formato del estudio.

| Módulo | Plan | Origen |
|---|---|---|
| **Agenda**: calendario de próximos contactos, promesas y cuotas por vencer; vista del día por ejecutivo | base | repo `agenda-cobranza` (calendario + gestiones por día) |
| **Recordatorios**: alertas internas (cuota vence mañana, promesa incumplida, próximo contacto) y aviso por correo al ejecutivo | profesional | — |
| **Calculadora 3-6-9 y acuerdos asistidos**: honorarios por tramos de UF, abono → capital/honorarios, plan de cuotas con interés y comisión Flow; crea el acuerdo directo en la cobranza y genera el Word | premium | repo `cobra369` (`calculos.js` ya portado como lógica de referencia) |
| **Avenimientos**: acuerdo judicial con su escrito para presentar | premium | depende del módulo judicial |
| **Mensaje de pago listo**: texto con monto, datos de transferencia y enlace; botón copiar / WhatsApp / correo | base | — |
| **UF del día** automática (para 3-6-9 y reajustes) | base | `cobra369/fetchUF.js` |

## Fase 3: judicial

- Causas con varios hitos (cuaderno, trámite, folio, fecha), litigantes,
  tribunal y rol; plazos procesales con vencimiento y alertas.
- Alertas de prescripción por tipo de documento.
- Escritos desde plantillas (demanda ejecutiva, avenimiento, etc.).
- **PJUD / Oficina Judicial Virtual**: el PJUD no ofrece una API pública. El
  camino es (1) importar lo que el abogado descarga o copia desde la OJV
  ("Mis causas", estado diario) y (2) si hace falta automatizar, contratar un
  proveedor con acceso autorizado. No se automatiza la Clave Única ni se
  saltan captchas. Se necesita un ejemplo real de lo que se exporta hoy.

## Fase 4: clientes y comunicaciones

- **Portal de mandantes**: el usuario con rol `mandante` ve su cartera,
  recupero, rendiciones y descarga sus informes (ya existe el rol y el
  vínculo `usuarios.cliente_id`).
- **Comunicaciones masivas**: envío de correos con la cuenta Workspace del
  estudio (Gmail API) y SMS (exportación en el formato de carga del portal
  Entel, o su API si el contrato la incluye); cada envío queda como gestión.
  Integrar los proyectos existentes de envío masivo.
- **Envío automático** de recordatorios de cuota y **pagos en línea**
  (Flow / Khipu / Webpay) con conciliación automática: premium.

## Fase 5: operación del SaaS

- Panel de plataforma (organizaciones, planes, uso) y facturación.
- Alta de organizaciones en autoservicio con período de prueba.
- Ley 21.719: aviso de privacidad, derechos ARCO, retención y borrado
  programado de datos de casos cerrados, registro de tratamientos.
- Monitoreo de errores (Sentry), logs centralizados, respaldos probados.
- Tareas en segundo plano (envíos, recordatorios, cargas grandes).

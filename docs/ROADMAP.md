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
Incluye el Word del acuerdo / avenimiento con el formato para aprobación del mandante.

| Módulo | Plan | Origen |
|---|---|---|
| **Agenda**: calendario de próximos contactos, promesas y cuotas por vencer; vista del día por ejecutivo | base | repo `agenda-cobranza` (calendario + gestiones por día) |
| **Recordatorios**: alertas internas (cuota vence mañana, promesa incumplida, próximo contacto) y aviso por correo al ejecutivo | profesional | — |
| **Calculadora 3-6-9 y acuerdos asistidos**: honorarios por tramos de UF, abono → capital/honorarios, plan de cuotas con interés y comisión Flow; crea el acuerdo directo en la cobranza y genera el Word | premium | repo `cobra369` (`calculos.js` ya portado como lógica de referencia) |
| **Avenimientos**: acuerdo judicial con su escrito para presentar | premium | depende del módulo judicial |
| **Mensaje de pago listo**: texto con monto, datos de transferencia y enlace; botón copiar / WhatsApp / correo | base | — |
| **UF del día** automática (para 3-6-9 y reajustes) | base | `cobra369/fetchUF.js` |

## Fase 3: judicial

- ✅ **Ciclo de vida de la cobranza**: ingreso → extrajudicial → para demanda
  → judicial (demanda, notificación, embargo, excepciones y sentencia, remate
  y pago) → término con motivo. Barra en la ficha de cada cobranza, historial
  de etapas, sin vuelta atrás desde judicial. Cada cliente fija a los cuántos
  días se sugiere demandar.
- ✅ **Causas** con varias cobranzas del mismo deudor (un rol), tribunales,
  abogado y procurador; **catálogo de trámites** con plazo de seguimiento,
  trámite siguiente, gasto y alerta (sacado del flujo procesal del sistema
  anterior del estudio); bandeja con plazos vencidos, de la semana y riesgo de
  abandono; plazos en la agenda; **embargos**; término de causa que cierra
  las cobranzas.
- ✅ **Gastos** por rendir al mandante, rendiciones por cliente, reembolso
  masivo y resumen de lo adeudado por cliente.
- ✅ Aviso de prescripción por tipo de documento antes de demandar
  (referencial, a confirmar por el abogado).
- Pendiente: litigantes y cuadernos, escritos desde plantillas (demanda
  ejecutiva, avenimiento, etc.), estudio corresponsal en pantalla
  (`cobranzas.estudio_a_cargo` ya existe), módulo judicial en la demo.
- **PJUD / Oficina Judicial Virtual**: el PJUD no ofrece una API pública. El
  camino es (1) importar lo que el abogado descarga o copia desde la OJV
  ("Mis causas", estado diario) y (2) si hace falta automatizar, contratar un
  proveedor con acceso autorizado. No se automatiza la Clave Única ni se
  saltan captchas. Se necesita un ejemplo real de lo que se exporta hoy.

## Fase 4: clientes y comunicaciones

- ✅ **Portal de mandantes** (plan profesional): el usuario con rol `mandante`
  entra a `/portal` y ve solo la cartera de su empresa: resumen con recupero
  mensual, ficha de cada caso (gestiones sin notas internas, acuerdo, pagos),
  aprobación u observación de acuerdos (queda como gestión en el caso) y
  descarga de recupero y rendición del mes. Se crea desde Usuarios con el
  rol "mandante" y su cliente.
- ✅ **Portal del deudor** (plan profesional): el ejecutivo genera desde la
  ficha un enlace personal (vence en 90 días, uno vigente por deudor) y lo
  manda por WhatsApp o correo. El deudor escribe su RUT y ve sus deudas, el
  avance de su convenio, cuotas atrasadas, próxima cuota, sus pagos y cómo
  pagar; nunca gestiones, notas, honorarios ni nombres del equipo. Cinco RUT
  equivocados bloquean el enlace. Cada día que lo abre queda una gestión
  automática en el caso. Pendiente: enviarlo solo junto con los recordatorios
  de cuota (envío automático, premium) y botón de pago en línea.
- **Comunicaciones masivas**: envío de correos con la cuenta Workspace del
  estudio (Gmail API) y SMS (exportación en el formato de carga del portal
  Entel, o su API si el contrato la incluye); cada envío queda como gestión.
  Integrar los proyectos existentes de envío masivo.
- **Envío automático** de recordatorios de cuota y **pagos en línea**
  (Flow / Khipu / Webpay) con conciliación automática: premium.

## Rendimiento (simulador)

`python -m app.cli simular --anios 5` llena una base de prueba con 5 años de
cartera con las proporciones de un estudio real (4.750 cobranzas, 60 mil
gestiones, 2.200 causas, 60 mil trámites, 4.200 pagos, 5.100 gastos) y
`medir-rendimiento` toma los tiempos. Medido en un PC de escritorio
(octubre 2026), sin red: listas, fichas y búsquedas entre 7 y 30 ms; bandeja
judicial 15–35 ms; avisos 32 ms; agenda del mes de todo el equipo ~115 ms;
panel ~70 ms. Volver a medir con `--anios 20` antes de migrar la cartera
histórica de un estudio.

## Fase 5: operación del SaaS

- Panel de plataforma (organizaciones, planes, uso) y facturación.
- Alta de organizaciones en autoservicio con período de prueba.
- Ley 21.719: aviso de privacidad, derechos ARCO, retención y borrado
  programado de datos de casos cerrados, registro de tratamientos.
- Monitoreo de errores (Sentry), logs centralizados, respaldos probados.
- Tareas en segundo plano (envíos, recordatorios, cargas grandes).

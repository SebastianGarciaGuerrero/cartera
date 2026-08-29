-- ============================================================
-- CARTERA — DDL Definitivo PostgreSQL 16
-- Versión: 1.0.0 | Fecha: 2026-06
-- ============================================================
-- CONVENCIONES:
--   PKs          → UUID (gen_random_uuid()) excepto catálogos (SERIAL)
--   Timestamps   → TIMESTAMPTZ siempre con zona horaria
--   RUTs         → VARCHAR(12) formato '12345678-9'
--   Montos       → NUMERIC(15,2) NUNCA FLOAT
--   Soft-delete  → campo 'activo BOOLEAN', nunca DELETE físico
--   Gestiones    → INMUTABLES, sin updated_at
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto"; -- gen_random_uuid()

-- ============================================================
-- [0] EMPRESA
-- Los datos de la empresa que USA el sistema (la que cobra).
-- Tabla de UNA SOLA FILA (id fijo = 1).
--
-- De aquí salen el membrete, la firma y el pie de página de
-- todos los documentos Word, y el nombre que se muestra en la
-- barra lateral. Es lo que hace que el sistema sea white-label:
-- cada instalación edita esta fila desde Configuración → Mi
-- empresa, sin tocar una línea de código.
-- ============================================================
CREATE TABLE empresa (
    id                 SMALLINT     PRIMARY KEY DEFAULT 1 CHECK (id = 1),

    -- Identidad legal
    razon_social       VARCHAR(200) NOT NULL,
    nombre_fantasia    VARCHAR(100),
    rut                VARCHAR(12),

    -- Membrete de los documentos
    wordmark           VARCHAR(100) NOT NULL,   -- línea grande del encabezado
    bajada             VARCHAR(150),            -- línea chica bajo el wordmark
    firma_documentos   VARCHAR(200),            -- nombre bajo la línea de firma

    -- Contacto (pie de las cartas)
    direccion          VARCHAR(200),
    ciudad             VARCHAR(100),
    horario_atencion   VARCHAR(120),
    telefonos          VARCHAR(120),
    emails             VARCHAR(200),
    sitio_web          VARCHAR(120),

    -- Formas de pago que se imprimen en el estado de cuenta.
    -- Texto libre, una forma de pago por línea.
    instrucciones_pago TEXT,

    updated_at         TIMESTAMPTZ  DEFAULT NOW()
);

-- Fila única con valores neutros: es la primera pantalla que
-- llena quien instala el sistema.
INSERT INTO empresa (
    id, razon_social, nombre_fantasia, wordmark, bajada,
    firma_documentos, ciudad, instrucciones_pago
) VALUES (
    1,
    'Mi Empresa de Cobranza SpA',
    'Mi Empresa',
    'MI EMPRESA DE COBRANZA',
    'GESTIÓN Y RECUPERO DE CARTERA',
    'Mi Empresa de Cobranza SpA',
    'Santiago, Chile',
    'Transferencia electrónica a la cuenta del cliente.'
);

-- ============================================================
-- [1] ROLES
-- Catálogo de roles. Separado de usuarios para poder
-- agregar roles nuevos sin tocar código.
-- Valores iniciales: admin, supervisor, operador, viewer
-- ============================================================
CREATE TABLE roles (
    id          SERIAL       PRIMARY KEY,
    nombre      VARCHAR(50)  NOT NULL UNIQUE,
    descripcion TEXT,
    created_at  TIMESTAMPTZ  DEFAULT NOW()
);

INSERT INTO roles (nombre, descripcion) VALUES
    ('admin',      'Acceso total, gestión de usuarios y configuración del sistema'),
    ('supervisor', 'Ve todos los registros, genera informes, carga masiva'),
    ('operador',   'Ingresa y edita gestiones de sus cobranzas asignadas'),
    ('viewer',     'Solo lectura sobre las cobranzas que se le asignen');

-- ============================================================
-- [2] USUARIOS
-- Las ~18 personas del equipo que usan el sistema.
-- ============================================================
CREATE TABLE usuarios (
    id             UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre         VARCHAR(100) NOT NULL,
    email          VARCHAR(150) NOT NULL UNIQUE,
    password_hash  VARCHAR(255) NOT NULL,      -- bcrypt, nunca texto plano
    rol_id         INTEGER      NOT NULL REFERENCES roles(id),
    activo         BOOLEAN      DEFAULT TRUE,
    ultimo_acceso  TIMESTAMPTZ,
    created_at     TIMESTAMPTZ  DEFAULT NOW(),
    updated_at     TIMESTAMPTZ  DEFAULT NOW()
);

-- ============================================================
-- [3] CLIENTES
-- Empresas mandantes que entregan su cartera para cobrar.
-- Ejemplo: una cadena de clínicas, una empresa de retail, una distribuidora.
-- Un cliente puede tener múltiples filiales.
-- ============================================================
CREATE TABLE clientes (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    rut             VARCHAR(12)  NOT NULL UNIQUE,
    razon_social    VARCHAR(200) NOT NULL,
    nombre_fantasia VARCHAR(200),
    direccion       TEXT,
    comuna          VARCHAR(100),
    ciudad          VARCHAR(100),
    telefono        VARCHAR(50),
    email           VARCHAR(150),
    activo          BOOLEAN      DEFAULT TRUE,
    created_at      TIMESTAMPTZ  DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  DEFAULT NOW()
);

-- ============================================================
-- [4] FILIALES
-- Sucursales de un cliente.
-- Ejemplo: Iquique, Elqui, Valparaíso, Rancagua,
--                   Temuco, Magallanes, Santiago, Providencia, Vitacura
-- Clientes sin sucursales tienen una filial "Principal".
-- ============================================================
CREATE TABLE filiales (
    id         SERIAL       PRIMARY KEY,
    cliente_id UUID         NOT NULL REFERENCES clientes(id),
    nombre     VARCHAR(100) NOT NULL,  -- 'Iquique', 'Valparaíso', 'Principal'
    activo     BOOLEAN      DEFAULT TRUE,
    created_at TIMESTAMPTZ  DEFAULT NOW(),
    UNIQUE (cliente_id, nombre)        -- no puede haber dos filiales con el mismo nombre en el mismo cliente
);

-- ============================================================
-- [5] PACIENTES
-- La persona que recibió la atención médica.
-- IMPORTANTE: puede ser DISTINTA del deudor.
-- Ejemplo: el paciente es el hijo menor de edad,
--          el deudor es el padre que firmó el pagaré.
-- Un paciente puede aparecer en múltiples cobranzas si
-- se atendió varias veces (una cobranza por atención).
-- ============================================================
CREATE TABLE pacientes (
    id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    rut         VARCHAR(12)  NOT NULL UNIQUE,  -- RUT del paciente
    nombre      VARCHAR(200) NOT NULL,
    fecha_nacimiento DATE,
    direccion   TEXT,
    departamento VARCHAR(50),
    comuna      VARCHAR(100),
    ciudad      VARCHAR(100),
    region      VARCHAR(100),
    observaciones TEXT,
    created_at  TIMESTAMPTZ  DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  DEFAULT NOW()
);

-- ============================================================
-- [6] CONTACTOS_PACIENTE
-- Teléfonos, emails y WhatsApp del paciente.
-- Tabla separada porque la cantidad es variable.
-- ============================================================
CREATE TABLE contactos_paciente (
    id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    paciente_id UUID         NOT NULL REFERENCES pacientes(id) ON DELETE CASCADE,
    tipo        VARCHAR(20)  NOT NULL CHECK (tipo IN ('telefono','celular','email','whatsapp','otro')),
    valor       VARCHAR(200) NOT NULL,
    activo      BOOLEAN      DEFAULT TRUE,
    created_at  TIMESTAMPTZ  DEFAULT NOW()
);

-- ============================================================
-- [7] DEUDORES
-- La persona que firmó el pagaré. Es A QUIEN SE LE COBRA.
-- CLAVE: un deudor puede tener múltiples cobranzas.
--   → Misma persona, distintas deudas (reincidente, varias atenciones)
--   → Cada cobranza tiene su propio N° interno e ID del cliente
--   → El RUT del deudor es la llave que agrupa todas sus deudas
-- ============================================================
CREATE TABLE deudores (
    id                    UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Identificación
    rut                   VARCHAR(12)  NOT NULL UNIQUE,  -- llave maestra del deudor
    tipo                  VARCHAR(10)  NOT NULL DEFAULT 'natural'
                              CHECK (tipo IN ('natural', 'juridica')),
    nombre                VARCHAR(200) NOT NULL,
    fecha_nacimiento      DATE,
    estado_civil          VARCHAR(30),
    nacionalidad          VARCHAR(60)  DEFAULT 'Chilena',
    -- Dirección
    direccion             TEXT,
    departamento          VARCHAR(50),
    comuna                VARCHAR(100),
    ciudad                VARCHAR(100),
    region                VARCHAR(100),
    -- Datos laborales
    empleador             VARCHAR(200),
    cargo                 VARCHAR(100),
    telefono_trabajo      VARCHAR(50),
    direccion_trabajo     TEXT,
    -- Contacto alternativo ("don Hugo" en las gestiones)
    contacto_alt_nombre   VARCHAR(200),
    contacto_alt_relacion VARCHAR(80),
    contacto_alt_telefono VARCHAR(50),
    -- Estado
    en_dicom              BOOLEAN      DEFAULT FALSE,
    observaciones         TEXT,
    created_at            TIMESTAMPTZ  DEFAULT NOW(),
    updated_at            TIMESTAMPTZ  DEFAULT NOW()
);

-- ============================================================
-- [8] CONTACTOS_DEUDOR
-- Teléfonos, emails y WhatsApp del deudor.
-- Sin límite de cantidad (tabla separada = normalización).
-- ============================================================
CREATE TABLE contactos_deudor (
    id         UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    deudor_id  UUID         NOT NULL REFERENCES deudores(id) ON DELETE CASCADE,
    tipo       VARCHAR(20)  NOT NULL CHECK (tipo IN ('telefono','celular','email','whatsapp','otro')),
    valor      VARCHAR(200) NOT NULL,
    activo     BOOLEAN      DEFAULT TRUE,
    created_at TIMESTAMPTZ  DEFAULT NOW()
);

-- ============================================================
-- [9] COBRANZAS
-- *** El núcleo del sistema. Una cobranza = una deuda. ***
--
-- IDENTIFICADORES:
--   numero     → N° de cobranza. ÚNICO GLOBAL. Autoincremental.
--                Generado por el sistema. NUNCA se repite, NUNCA cambia.
--                Ejemplo: 14220
--
--   id_externo → ID de la cobranza en el sistema del cliente.
--                ÚNICO POR CLIENTE (restricción compuesta cliente_id + id_externo).
--                Dos clientes distintos pueden tener el mismo número.
--                Ejemplo: "122838" en el sistema del cliente
--
-- DEUDOR vs PACIENTE:
--   deudor_id  → quien firmó el pagaré, a quien se le cobra
--   paciente_id → quien recibió la atención (puede ser otro RUT)
--
-- UN DEUDOR → N COBRANZAS:
--   Mismo deudor puede tener varias cobranzas (deudas distintas).
--   Cada cobranza tiene su propio numero interno e id_externo (el del cliente).
--   El sistema agrupa por deudor_id para mostrar todas las deudas de una persona.
--
-- ESTADOS:
--   activa        → en gestión extrajudicial normal
--   acuerdo_pago  → tiene acuerdo de pago vigente
--   judicial      → pasó a tribunal
--   pagada        → cobrada totalmente
--   archivada     → cerrada sin pago total
--   castigo       → incobrable, dado de baja contable
-- ============================================================
CREATE TABLE cobranzas (
    -- Identificadores
    id                       UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    numero                   INTEGER       NOT NULL UNIQUE
                                 GENERATED ALWAYS AS IDENTITY
                                 (START WITH 20000 INCREMENT BY 1),
    -- numero usa IDENTITY (PostgreSQL 10+): se genera automáticamente,
    -- NO se puede insertar un valor manual. Garantiza unicidad absoluta.
    -- Arranca en 20000: el sistema legacy maneja N° desde 10000 y va por
    -- los 14000, así que 20000 deja margen para no chocar con esos rangos.

    -- Vínculos principales
    cliente_id               UUID          NOT NULL REFERENCES clientes(id),
    filial_id                INTEGER       REFERENCES filiales(id),
    deudor_id                UUID          NOT NULL REFERENCES deudores(id),
    paciente_id              UUID          REFERENCES pacientes(id),
    -- paciente_id puede ser NULL si deudor y paciente son la misma persona
    -- En ese caso, el RUT del deudor = RUT del paciente

    -- Identificadores externos
    id_externo               VARCHAR(50),
    -- UNIQUE por cliente: mismo cliente no puede tener dos cobranzas con el mismo ID
    numero_liquidacion       VARCHAR(50),

    -- Montos
    monto_original           NUMERIC(15,2) NOT NULL,  -- deuda al momento de ingreso
    monto_actual             NUMERIC(15,2) NOT NULL,  -- se actualiza con cada pago
    -- Desglose (columnas que completa la empresa de cobranza)
    capital                  NUMERIC(15,2),
    intereses                NUMERIC(15,2) DEFAULT 0,
    honorarios               NUMERIC(15,2) DEFAULT 0,
    gastos                   NUMERIC(15,2) DEFAULT 0,

    -- Fechas de la atención médica
    fecha_atencion           DATE,         -- fecha de la prestación/operación de origen
    fecha_alta               DATE,         -- fecha de alta o cierre de la prestación
    prevision                VARCHAR(80),  -- FONASA / BANMEDICA / CONSALUD / etc.

    -- Fechas operacionales
    fecha_ingreso            DATE          NOT NULL DEFAULT CURRENT_DATE,  -- cuando entró a cobranza
    fecha_traspaso           DATE,         -- cuando el cliente derivó a cobranza judicial

    -- Documento que identifica la deuda (para clínicas es el pagaré;
    -- también hay facturas, letras, cheques...)
    tipo_documento           VARCHAR(30)   DEFAULT 'pagare'
                                 CHECK (tipo_documento IN
                                     ('pagare','factura','letra','cheque','otro')),
    numero_pagare            VARCHAR(50),  -- N° del documento
    fecha_ejecucion_pagare   DATE,
    fecha_vencimiento_pagare DATE,
    comprobante_envio        VARCHAR(200), -- N° Chilexpress o Correos Chile
    autorizacion_firma       BOOLEAN       DEFAULT FALSE,
    fecha_envio_documentos   DATE,

    -- Estado y tipo
    estado                   VARCHAR(20)   NOT NULL DEFAULT 'activa'
                                 CHECK (estado IN (
                                     'activa',
                                     'acuerdo_pago',
                                     'judicial',
                                     'pagada',
                                     'archivada',
                                     'castigo'
                                 )),
    tipo                     VARCHAR(20)   NOT NULL DEFAULT 'extrajudicial'
                                 CHECK (tipo IN ('extrajudicial','judicial')),
    etapa_cobranza           VARCHAR(50),  -- texto libre de la clínica: 'Judicial', 'Sólo extrajudicial', etc.

    -- Ejecutivo responsable
    ejecutivo_id             UUID          REFERENCES usuarios(id),

    observaciones            TEXT,
    created_at               TIMESTAMPTZ   DEFAULT NOW(),
    updated_at               TIMESTAMPTZ   DEFAULT NOW(),

    -- RESTRICCIÓN CLAVE: id_externo único por cliente
    CONSTRAINT uq_cobranza_id_externo UNIQUE (cliente_id, id_externo)
);

-- ============================================================
-- [10] TIPOS_GESTION
-- Catálogo de tipos para clasificar y filtrar gestiones.
-- ============================================================
CREATE TABLE tipos_gestion (
    id     SERIAL       PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL UNIQUE,
    activo BOOLEAN      DEFAULT TRUE
);

INSERT INTO tipos_gestion (nombre) VALUES
    ('Llamada telefónica'),
    ('Email enviado'),
    ('WhatsApp'),
    ('Carta de cobranza'),
    ('Acuerdo de pago'),
    ('Visita en terreno'),
    ('Nota interna'),
    ('Gestión automática'),
    ('Cobranza ingresada al sistema'),
    ('Demanda presentada'),
    ('Pagaré ejecutado'),
    ('Acuerdo incumplido'),
    ('Abono'),
    ('Pagado');

-- ============================================================
-- [11] GESTIONES
-- CORAZÓN del sistema. Cada acción realizada con el deudor.
--
-- REGLA ABSOLUTA: las gestiones son INMUTABLES.
--   - Sin updated_at (no se edita)
--   - Sin endpoint PUT /gestiones/:id
--   - Si hay un error → se agrega una gestión correctiva
--   - Esto protege la integridad del historial legal
-- ============================================================
CREATE TABLE gestiones (
    id                     UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    cobranza_id            UUID         NOT NULL REFERENCES cobranzas(id) ON DELETE RESTRICT,
    usuario_id             UUID         NOT NULL REFERENCES usuarios(id),
    fecha_gestion          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    tipo_id                INTEGER      REFERENCES tipos_gestion(id),
    descripcion            TEXT         NOT NULL,
    fecha_proximo_contacto DATE,
    es_masivo              BOOLEAN      NOT NULL DEFAULT FALSE,  -- cargada en bloque
    created_at             TIMESTAMPTZ  DEFAULT NOW()
    -- SIN updated_at → INMUTABLE por diseño
);

-- ============================================================
-- [12] ACUERDOS_PAGO
-- Acuerdo formal de pago con el deudor.
-- Una cobranza puede tener varios acuerdos en el tiempo
-- (renegociaciones). Solo uno puede estar 'vigente' a la vez.
--
-- El desglose (capital + honorarios + intereses)
-- es la base del cuadro de rendición mensual a la clínica.
-- ============================================================
CREATE TABLE acuerdos_pago (
    id                   UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    cobranza_id          UUID          NOT NULL REFERENCES cobranzas(id),

    -- Fechas
    fecha_acuerdo        DATE          NOT NULL DEFAULT CURRENT_DATE,
    fecha_termino        DATE,         -- calculada al crear, guardada para referencia

    -- Montos del acuerdo
    pie                  NUMERIC(15,2) DEFAULT 0,     -- pago inicial antes de cuotas
    monto_total_acordado NUMERIC(15,2) NOT NULL,       -- total incluyendo todo
    numero_cuotas        INTEGER       NOT NULL DEFAULT 1,
    dia_pago             INTEGER       CHECK (dia_pago BETWEEN 1 AND 31),
    fecha_primera_cuota  DATE          NOT NULL,

    -- Desglose del monto acordado (para rendición)
    capital              NUMERIC(15,2) DEFAULT 0,
    honorarios           NUMERIC(15,2) DEFAULT 0,
    intereses            NUMERIC(15,2) DEFAULT 0,
    gastos_judiciales    NUMERIC(15,2) DEFAULT 0,

    -- Estado del acuerdo
    estado               VARCHAR(20)   NOT NULL DEFAULT 'vigente'
                             CHECK (estado IN (
                                 'vigente',
                                 'cumplido',
                                 'incumplido',
                                 'renegociado'
                             )),
    tipo_pago            VARCHAR(20)   DEFAULT 'extrajudicial'
                             CHECK (tipo_pago IN ('extrajudicial','abonos')),

    -- Firma del cliente (el mandante debe aprobar el acuerdo)
    firma_cliente        VARCHAR(30)   DEFAULT 'sin_firmar'
                             CHECK (firma_cliente IN (
                                 'sin_firmar',
                                 'pendiente',
                                 'firmado_confirmado'
                             )),
    fecha_firma          DATE,

    -- Registro
    usuario_id           UUID          NOT NULL REFERENCES usuarios(id),
    observaciones        TEXT,
    created_at           TIMESTAMPTZ   DEFAULT NOW()
    -- Sin updated_at: si se renegocia, el estado cambia a 'renegociado'
    -- y se crea un acuerdo nuevo. El historial queda intacto.
);

-- ============================================================
-- [13] CUOTAS
-- Cada cuota individual de un acuerdo de pago.
-- Se generan AUTOMÁTICAMENTE al crear el acuerdo.
-- El backend crea N filas calculando las fechas de vencimiento.
-- ============================================================
CREATE TABLE cuotas (
    id                UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    acuerdo_id        UUID          NOT NULL REFERENCES acuerdos_pago(id) ON DELETE CASCADE,
    numero_cuota      INTEGER       NOT NULL,           -- 1, 2, 3...
    monto             NUMERIC(15,2) NOT NULL,            -- monto comprometido
    fecha_vencimiento DATE          NOT NULL,            -- cuándo vence esta cuota
    monto_pagado      NUMERIC(15,2) NOT NULL DEFAULT 0, -- acumulado (puede ser pago parcial)
    estado            VARCHAR(20)   NOT NULL DEFAULT 'pendiente'
                          CHECK (estado IN (
                              'pendiente',
                              'pagada',
                              'vencida',
                              'pagada_parcial'
                          )),
    UNIQUE (acuerdo_id, numero_cuota)
);

-- ============================================================
-- [14] PAGOS
-- Cada pago real recibido. Es la fuente del recupero mensual.
-- Reemplaza la planilla Excel de recupero.
--
-- Un pago puede:
--   a) Asociarse a una cuota específica (cuota_id NOT NULL)
--   b) Ser pago directo sin acuerdo (cuota_id NULL)
--   c) Ser un abono parcial sin cuota formal
--
-- Al registrar un pago (transacción atómica):
--   1. Se descuenta de cobranzas.monto_actual
--   2. Si tiene cuota_id → se actualiza cuotas.monto_pagado y estado
--   3. Si todas las cuotas del acuerdo están pagadas →
--      acuerdo pasa a 'cumplido', cobranza pasa a 'pagada'
--
-- DESGLOSE: cada pago se divide en capital+honorarios+interés
--   → capital + intereses = lo que se rinde a la clínica
--   → honorarios = ingreso de la empresa de cobranza
-- ============================================================
CREATE TABLE pagos (
    id                  UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    cobranza_id         UUID          NOT NULL REFERENCES cobranzas(id),
    cuota_id            UUID          REFERENCES cuotas(id),  -- NULL si pago directo

    -- Fecha real del pago (puede diferir de la fecha de registro)
    fecha_pago          DATE          NOT NULL DEFAULT CURRENT_DATE,

    -- Monto total
    monto               NUMERIC(15,2) NOT NULL,

    -- Desglose del pago (para cuadro de rendición)
    -- El CAPITAL es la guía: es lo único que descuenta el saldo de la
    -- cobranza. Honorarios/interés varían según el abono y la UF del día.
    capital             NUMERIC(15,2) DEFAULT 0,
    honorarios          NUMERIC(15,2) DEFAULT 0,
    intereses           NUMERIC(15,2) DEFAULT 0,
    gastos_judiciales   NUMERIC(15,2) DEFAULT 0,

    -- Forma de pago
    forma_pago          VARCHAR(30)
                            CHECK (forma_pago IN (
                                'transferencia','cheque','efectivo',
                                'deposito','flow','presencial',
                                'bonificacion','otro'
                            )),
    numero_comprobante  VARCHAR(100),  -- N° transferencia, folio, etc.

    -- Estado normalizado
    estado_pago         VARCHAR(20)   NOT NULL DEFAULT 'pagado'
                            CHECK (estado_pago IN (
                                'pagado',    -- deuda saldada completamente
                                'abono',     -- pago parcial sin acuerdo formal
                                'cuota',     -- pago de una cuota de acuerdo
                                'bonificacion'
                            )),
    descripcion_estado  TEXT,         -- texto libre original del Excel (para auditoría)

    -- Quién registró
    usuario_id          UUID          NOT NULL REFERENCES usuarios(id),
    observaciones       TEXT,
    created_at          TIMESTAMPTZ   DEFAULT NOW()
    -- Sin updated_at: los pagos son inmutables (igual que gestiones)
);

-- ============================================================
-- [15] GESTIONES_JUDICIALES
-- Info adicional cuando la cobranza pasa a tribunal.
-- Relación 1-a-1 con cobranzas (UNIQUE en cobranza_id).
-- ============================================================
CREATE TABLE gestiones_judiciales (
    id             UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    cobranza_id    UUID         NOT NULL UNIQUE REFERENCES cobranzas(id),
    numero_rol     VARCHAR(50),
    tribunal       VARCHAR(200),
    fecha_ingreso  DATE,
    estado_proceso VARCHAR(100),
    abogado_id     UUID         REFERENCES usuarios(id),
    observaciones  TEXT,
    created_at     TIMESTAMPTZ  DEFAULT NOW(),
    updated_at     TIMESTAMPTZ  DEFAULT NOW()
);

-- ============================================================
-- [16] AUDIT_LOG
-- Registro INMUTABLE de todas las acciones del sistema.
-- Nunca se borra ni se modifica. Solo INSERT.
-- Cumple Ley 21.719 de Protección de Datos Personales (Chile).
-- Implementar con triggers en tablas críticas.
-- ============================================================
CREATE TABLE audit_log (
    id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id       UUID         REFERENCES usuarios(id),
    accion           VARCHAR(10)  NOT NULL CHECK (accion IN ('INSERT','UPDATE','DELETE')),
    tabla            VARCHAR(100) NOT NULL,
    registro_id      TEXT         NOT NULL,   -- UUID o número del registro afectado
    datos_anteriores JSONB,                   -- estado antes del cambio
    datos_nuevos     JSONB,                   -- estado después del cambio
    ip_origen        VARCHAR(45),
    created_at       TIMESTAMPTZ  DEFAULT NOW()
);

-- ============================================================
-- ÍNDICES DE PERFORMANCE
-- Sin índice → full table scan en 2.6M registros = lento.
-- Con índice → O(log n) = casi instantáneo.
-- ============================================================

-- Cobranzas: las búsquedas más frecuentes
CREATE UNIQUE INDEX idx_cobranzas_numero
    ON cobranzas(numero);
    -- Ya es UNIQUE en la columna, pero el índice explícito es más rápido

CREATE INDEX idx_cobranzas_id_externo
    ON cobranzas(id_externo);
    -- Para buscar por ID de la clínica

CREATE INDEX idx_cobranzas_cliente_filial
    ON cobranzas(cliente_id, filial_id);

CREATE INDEX idx_cobranzas_deudor
    ON cobranzas(deudor_id);
    -- Para ver TODAS las cobranzas de un mismo deudor (reincidentes)

CREATE INDEX idx_cobranzas_paciente
    ON cobranzas(paciente_id);

CREATE INDEX idx_cobranzas_estado
    ON cobranzas(estado);

CREATE INDEX idx_cobranzas_ejecutivo
    ON cobranzas(ejecutivo_id);

-- Deudores y pacientes: búsqueda por RUT
CREATE UNIQUE INDEX idx_deudores_rut
    ON deudores(rut);

CREATE UNIQUE INDEX idx_pacientes_rut
    ON pacientes(rut);

CREATE INDEX idx_deudores_nombre
    ON deudores USING gin(to_tsvector('spanish', nombre));
    -- Búsqueda de texto libre por nombre (PostgreSQL full-text search)

-- Gestiones: las más consultadas por volumen
CREATE INDEX idx_gestiones_cobranza
    ON gestiones(cobranza_id);

CREATE INDEX idx_gestiones_fecha
    ON gestiones(fecha_gestion DESC);

CREATE INDEX idx_gestiones_usuario
    ON gestiones(usuario_id);

CREATE INDEX idx_gestiones_prox_contacto
    ON gestiones(fecha_proximo_contacto)
    WHERE fecha_proximo_contacto IS NOT NULL;
    -- Índice parcial: solo filas con próximo contacto

-- Pagos: recupero mensual
CREATE INDEX idx_pagos_cobranza
    ON pagos(cobranza_id);

CREATE INDEX idx_pagos_fecha
    ON pagos(fecha_pago DESC);

CREATE INDEX idx_pagos_cliente_mes
    ON pagos(fecha_pago, cobranza_id);
    -- Para generar recupero mensual filtrado por mes

-- Cuotas
CREATE INDEX idx_cuotas_acuerdo
    ON cuotas(acuerdo_id);

CREATE INDEX idx_cuotas_vencimiento
    ON cuotas(fecha_vencimiento)
    WHERE estado = 'pendiente';
    -- Índice parcial: solo cuotas pendientes para alertas de vencimiento

-- Acuerdos
CREATE INDEX idx_acuerdos_cobranza
    ON acuerdos_pago(cobranza_id);

CREATE INDEX idx_acuerdos_vigentes
    ON acuerdos_pago(cobranza_id)
    WHERE estado = 'vigente';
    -- Índice parcial: solo acuerdos vigentes (los que más se consultan)

-- Audit log
CREATE INDEX idx_audit_tabla_registro
    ON audit_log(tabla, registro_id);

CREATE INDEX idx_audit_usuario_fecha
    ON audit_log(usuario_id, created_at DESC);

-- ============================================================
-- VISTAS
-- No ocupan espacio, siempre actualizadas automáticamente.
-- ============================================================

-- Vista: recupero mensual (reemplaza el Excel de recupero)
CREATE VIEW vista_recupero AS
SELECT
    p.id                                    AS pago_id,
    p.fecha_pago,
    date_trunc('month', p.fecha_pago)::date AS mes,
    c.numero                                AS numero_cobranza,
    c.id_externo,
    cl.razon_social                         AS cliente,
    f.nombre                                AS filial,
    d.nombre                                AS deudor,
    d.rut                                   AS rut_deudor,
    p.monto                                 AS total_recibido,
    p.capital,
    p.honorarios,
    p.intereses,
    p.estado_pago,
    p.descripcion_estado,
    p.forma_pago,
    p.numero_comprobante,
    cu.numero_cuota,
    ap.numero_cuotas                        AS total_cuotas_acuerdo,
    u.nombre                                AS registrado_por,
    p.gastos_judiciales
FROM pagos p
JOIN cobranzas c    ON c.id = p.cobranza_id
JOIN clientes cl    ON cl.id = c.cliente_id
JOIN deudores d     ON d.id = c.deudor_id
JOIN usuarios u     ON u.id = p.usuario_id
LEFT JOIN filiales f         ON f.id = c.filial_id
LEFT JOIN cuotas cu          ON cu.id = p.cuota_id
LEFT JOIN acuerdos_pago ap   ON ap.id = cu.acuerdo_id;

-- Vista: resumen de deudas por deudor
-- Para ver TODAS las cobranzas de una misma persona (reincidentes)
CREATE VIEW vista_deudor_cobranzas AS
SELECT
    d.id                                     AS deudor_id,
    d.rut,
    d.nombre                                 AS deudor,
    count(c.id)                              AS total_cobranzas,
    count(c.id) FILTER (WHERE c.estado = 'activa')        AS cobranzas_activas,
    count(c.id) FILTER (WHERE c.estado = 'acuerdo_pago')  AS en_acuerdo,
    count(c.id) FILTER (WHERE c.estado = 'pagada')        AS pagadas,
    count(c.id) FILTER (WHERE c.estado = 'judicial')      AS judiciales,
    sum(c.monto_original)                    AS total_deuda_original,
    sum(c.monto_actual)                      AS total_deuda_actual
FROM deudores d
LEFT JOIN cobranzas c ON c.deudor_id = d.id
GROUP BY d.id, d.rut, d.nombre;

-- Vista: cuadro de rendición (lo que se envía al cliente)
CREATE VIEW vista_rendicion AS
SELECT
    date_trunc('month', p.fecha_pago)::date  AS mes,
    cl.razon_social                           AS cliente,
    f.nombre                                  AS filial,
    count(p.id)                               AS cantidad_pagos,
    sum(p.capital)                            AS total_capital,
    sum(p.honorarios)                         AS total_honorarios,
    sum(p.intereses)                          AS total_intereses,
    sum(p.capital + p.intereses)              AS total_a_rendir_cliente,
    sum(p.monto)                              AS total_recibido
FROM pagos p
JOIN cobranzas c  ON c.id = p.cobranza_id
JOIN clientes cl  ON cl.id = c.cliente_id
LEFT JOIN filiales f ON f.id = c.filial_id
GROUP BY
    date_trunc('month', p.fecha_pago),
    cl.razon_social,
    f.nombre
ORDER BY mes DESC, cliente, filial;

-- Vista: acuerdos con estado de atraso (reemplaza dashboard Excel)
CREATE VIEW vista_acuerdos_estado AS
SELECT
    ap.id                                    AS acuerdo_id,
    c.numero                                 AS numero_cobranza,
    c.id_externo,
    cl.razon_social                          AS cliente,
    f.nombre                                 AS filial,
    d.nombre                                 AS deudor,
    d.rut,
    ap.pie,
    ap.monto_total_acordado,
    ap.numero_cuotas,
    ap.dia_pago,
    ap.fecha_acuerdo,
    ap.fecha_termino,
    ap.firma_cliente,
    ap.estado,
    -- Cuotas calculadas
    count(cu.id) FILTER (WHERE cu.estado = 'pagada')   AS cuotas_pagadas,
    count(cu.id) FILTER (WHERE cu.estado = 'pendiente'
                           OR cu.estado = 'pagada_parcial'
                           OR cu.estado = 'vencida')   AS cuotas_pendientes,
    -- Meses de atraso: cuotas vencidas sin pagar
    count(cu.id) FILTER (WHERE cu.estado = 'vencida')  AS meses_atraso
FROM acuerdos_pago ap
JOIN cobranzas c  ON c.id = ap.cobranza_id
JOIN clientes cl  ON cl.id = c.cliente_id
JOIN deudores d   ON d.id = c.deudor_id
LEFT JOIN filiales f ON f.id = c.filial_id
LEFT JOIN cuotas cu  ON cu.acuerdo_id = ap.id
WHERE ap.estado = 'vigente'
GROUP BY
    ap.id, c.numero, c.id_externo,
    cl.razon_social, f.nombre, d.nombre, d.rut,
    ap.pie, ap.monto_total_acordado, ap.numero_cuotas,
    ap.dia_pago, ap.fecha_acuerdo, ap.fecha_termino,
    ap.firma_cliente, ap.estado;

-- ============================================================
-- FIN DEL DDL
-- Tablas: 17
-- Índices: 17 (incluyendo 3 parciales)
-- Vistas: 4
-- ============================================================

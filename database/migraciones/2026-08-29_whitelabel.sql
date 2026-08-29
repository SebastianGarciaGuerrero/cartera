-- ============================================================
-- Migración: rebranding white-label
-- Fecha: 2026-08-29
--
-- Renombra las columnas que llevaban el nombre del primer
-- cliente del sistema y crea la tabla `empresa` (los datos
-- institucionales que salen en los documentos Word).
--
-- Correr UNA sola vez, sobre bases creadas con el DDL anterior:
--   psql -U cartera_admin -d cartera -f 2026-08-29_whitelabel.sql
--
-- Bases nuevas NO la necesitan: 001_schema.sql ya viene con los
-- nombres nuevos.
-- ============================================================

BEGIN;

-- ------------------------------------------------------------
-- 1) Las vistas se recrean al final. Hay que soltarlas primero
--    porque PostgreSQL sigue el rename de la columna pero deja
--    el alias viejo en el nombre de salida de la vista.
-- ------------------------------------------------------------
DROP VIEW IF EXISTS vista_recupero;
DROP VIEW IF EXISTS vista_rendicion;
DROP VIEW IF EXISTS vista_acuerdos_estado;

-- ------------------------------------------------------------
-- 2) Renombre de columnas
--
-- Va dentro de un DO para que sea idempotente: cada rename se
-- aplica solo si la columna vieja todavía existe. Así la
-- migración se puede volver a correr sin reventar, y tampoco
-- falla si alguien ya renombró una parte a mano.
-- ------------------------------------------------------------
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT * FROM (VALUES
            ('cobranzas',     'id_clinica',          'id_externo'),
            ('cobranzas',     'capital_hadad',       'capital'),
            ('cobranzas',     'intereses_hadad',     'intereses'),
            ('cobranzas',     'honorarios_hadad',    'honorarios'),
            ('cobranzas',     'gastos_hadad',        'gastos'),
            ('cobranzas',     'fecha_ingreso_hadad', 'fecha_ingreso'),
            ('pagos',         'capital_clinica',     'capital'),
            ('pagos',         'honorarios_hadad',    'honorarios'),
            ('pagos',         'interes_clinica',     'intereses'),
            ('acuerdos_pago', 'capital_clinica',     'capital'),
            ('acuerdos_pago', 'honorarios_hadad',    'honorarios'),
            ('acuerdos_pago', 'interes_clinica',     'intereses'),
            ('acuerdos_pago', 'firma_clinica',       'firma_cliente')
        ) AS t(tabla, viejo, nuevo)
    LOOP
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = r.tabla
              AND column_name = r.viejo
        ) THEN
            EXECUTE format('ALTER TABLE %I RENAME COLUMN %I TO %I',
                           r.tabla, r.viejo, r.nuevo);
            RAISE NOTICE 'renombrada %.% -> %', r.tabla, r.viejo, r.nuevo;
        END IF;
    END LOOP;
END $$;

-- ------------------------------------------------------------
-- 3) Nombres de la restricción única y del índice
--
-- Son cosméticos (funcionan igual con el nombre viejo), así que
-- también van condicionados: si tu base los nombró distinto, la
-- migración sigue de largo en vez de abortar.
-- ------------------------------------------------------------
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_cobranza_clinica') THEN
        ALTER TABLE cobranzas
            RENAME CONSTRAINT uq_cobranza_clinica TO uq_cobranza_id_externo;
    END IF;

    -- El CHECK de la firma lo nombró PostgreSQL solo a partir del
    -- nombre de la columna vieja; sigue validando bien tras el rename.
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'acuerdos_pago_firma_clinica_check') THEN
        ALTER TABLE acuerdos_pago
            RENAME CONSTRAINT acuerdos_pago_firma_clinica_check
                           TO acuerdos_pago_firma_cliente_check;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'idx_cobranzas_id_clinica') THEN
        ALTER INDEX idx_cobranzas_id_clinica RENAME TO idx_cobranzas_id_externo;
    END IF;
END $$;

-- ------------------------------------------------------------
-- 4) EMPRESA (nueva tabla, fila única)

-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS empresa (
    id                 SMALLINT     PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    razon_social       VARCHAR(200) NOT NULL,
    nombre_fantasia    VARCHAR(100),
    rut                VARCHAR(12),
    wordmark           VARCHAR(100) NOT NULL,
    bajada             VARCHAR(150),
    firma_documentos   VARCHAR(200),
    direccion          VARCHAR(200),
    ciudad             VARCHAR(100),
    horario_atencion   VARCHAR(120),
    telefonos          VARCHAR(120),
    emails             VARCHAR(200),
    sitio_web          VARCHAR(120),
    instrucciones_pago TEXT,
    updated_at         TIMESTAMPTZ  DEFAULT NOW()
);

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
)
ON CONFLICT (id) DO NOTHING;

-- ------------------------------------------------------------
-- 5) Vistas, con los nombres de salida nuevos
-- ------------------------------------------------------------
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

-- Vista: cuadro de rendición al cliente
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

-- Vista: acuerdos vigentes con estado de atraso
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

COMMIT;

-- Comprobación rápida después de correrla:
--   \d cobranzas
--   SELECT * FROM empresa;
--   SELECT * FROM vista_rendicion LIMIT 1;

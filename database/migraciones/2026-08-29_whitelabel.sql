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
-- 2) COBRANZAS
-- ------------------------------------------------------------
ALTER TABLE cobranzas RENAME COLUMN id_clinica          TO id_externo;
ALTER TABLE cobranzas RENAME COLUMN capital_hadad       TO capital;
ALTER TABLE cobranzas RENAME COLUMN intereses_hadad     TO intereses;
ALTER TABLE cobranzas RENAME COLUMN honorarios_hadad    TO honorarios;
ALTER TABLE cobranzas RENAME COLUMN gastos_hadad        TO gastos;
ALTER TABLE cobranzas RENAME COLUMN fecha_ingreso_hadad TO fecha_ingreso;

ALTER TABLE cobranzas RENAME CONSTRAINT uq_cobranza_clinica TO uq_cobranza_id_externo;
ALTER INDEX idx_cobranzas_id_clinica RENAME TO idx_cobranzas_id_externo;

-- ------------------------------------------------------------
-- 3) PAGOS
-- ------------------------------------------------------------
ALTER TABLE pagos RENAME COLUMN capital_clinica  TO capital;
ALTER TABLE pagos RENAME COLUMN honorarios_hadad TO honorarios;
ALTER TABLE pagos RENAME COLUMN interes_clinica  TO intereses;

-- ------------------------------------------------------------
-- 4) ACUERDOS DE PAGO
-- ------------------------------------------------------------
ALTER TABLE acuerdos_pago RENAME COLUMN capital_clinica  TO capital;
ALTER TABLE acuerdos_pago RENAME COLUMN honorarios_hadad TO honorarios;
ALTER TABLE acuerdos_pago RENAME COLUMN interes_clinica  TO intereses;
ALTER TABLE acuerdos_pago RENAME COLUMN firma_clinica    TO firma_cliente;

-- El CHECK viejo sigue apuntando bien a la columna renombrada,
-- solo se le cambia el nombre para que no diga 'clinica'.
ALTER TABLE acuerdos_pago
    RENAME CONSTRAINT acuerdos_pago_firma_clinica_check TO acuerdos_pago_firma_cliente_check;

-- ------------------------------------------------------------
-- 5) EMPRESA (nueva tabla, fila única)
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
-- 6) Vistas, con los nombres de salida nuevos
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

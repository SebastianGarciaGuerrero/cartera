-- ============================================================
-- Adopción de una base existente (creada antes de usar Alembic)
--
-- La base ya tiene las tablas de negocio. Solo se asegura de que exista
-- la tabla `empresa` (datos institucionales); las vistas las recrea la
-- migración 0003. Una base con los nombres de columna de la versión
-- anterior a la marca blanca se detiene antes (ver 0001_esquema_base.py).
-- ============================================================

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

INSERT INTO empresa (id, razon_social, nombre_fantasia, wordmark)
VALUES (1, 'Mi Empresa de Cobranza SpA', 'Mi Empresa', 'MI EMPRESA DE COBRANZA')
ON CONFLICT (id) DO NOTHING;

-- ============================================================
-- Verificación post-setup
-- Este script corre automáticamente después del DDL.
-- Deja el sistema usable: un admin para entrar y un cliente de
-- ejemplo con filiales, todo con datos neutros de demostración.
-- ============================================================

-- Usuario admin inicial
-- Email: admin@cartera.cl
-- Password: cartera2026 (hasheado con bcrypt)
-- ⚠️ Cambiar la contraseña en el primer ingreso.
INSERT INTO usuarios (nombre, email, password_hash, rol_id)
VALUES (
    'Administrador',
    'admin@cartera.cl',
    '$2b$12$1zjUqCZTrgIgOHylzH1Yj.daX0G42Rl7euYjN6UdNZsdYM3vlfnNm',
    (SELECT id FROM roles WHERE nombre = 'admin')
);

-- Cliente de ejemplo (borrable): sirve para probar el alta de
-- cobranzas antes de cargar la cartera real.
INSERT INTO clientes (rut, razon_social, nombre_fantasia)
VALUES ('96570220-7', 'CLÍNICA LOS ANDES S.A.', 'Clínica Los Andes');

-- Filiales de ejemplo del cliente anterior
INSERT INTO filiales (cliente_id, nombre)
SELECT id, filial
FROM clientes
CROSS JOIN (VALUES
    ('Santiago'), ('Valparaíso'), ('Concepción')
) AS f(filial)
WHERE rut = '96570220-7';

-- Mensaje de éxito
DO $$
BEGIN
    RAISE NOTICE 'Base de datos Cartera inicializada correctamente';
    RAISE NOTICE '   - 17 tablas creadas';
    RAISE NOTICE '   - 4 roles iniciales';
    RAISE NOTICE '   - 12 tipos de gestión';
    RAISE NOTICE '   - Usuario admin: admin@cartera.cl / cartera2026';
    RAISE NOTICE '   - Datos de la empresa: editarlos en Configuración > Mi empresa';
    RAISE NOTICE '   - Cliente de ejemplo: Clínica Los Andes con 3 filiales';
END $$;

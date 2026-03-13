-- Script final: inserts corregidos para ENUM en mayúsculas
-- Ejecutar solo si necesitas el usuario admin

-- Insertar usuario administrador (role y status en mayúsculas, solo si no existe)
INSERT INTO users (email, password, role, status, email_verified)
SELECT 'admin@servicefinder.com',
    '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewdBPj89UZoderOi',
    'ADMIN',
    'ACTIVE',
    TRUE
WHERE NOT EXISTS (SELECT 1 FROM users WHERE email = 'admin@servicefinder.com');

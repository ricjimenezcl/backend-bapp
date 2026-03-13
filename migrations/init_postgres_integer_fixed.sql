-- Script adaptado para PostgreSQL con ids integer y ENUM en mayúsculas
-- Ejecutar solo los inserts si las tablas ya existen

-- Insertar categorías de servicio (sin ON CONFLICT)
INSERT INTO service_categories (name, description, icon) VALUES
('electricista', 'Servicios eléctricos residenciales e industriales', 'flash'),
('mecanico', 'Reparación y mantenimiento de vehículos', 'car'),
('vulcanizacion', 'Reparación y cambio de neumáticos', 'build'),
('gruas', 'Servicios de grúa y transporte vehicular', 'trail-sign'),
('aseo', 'Limpieza residencial y comercial', 'home'),
('jardineria', 'Mantenimiento de jardines y áreas verdes', 'leaf'),
('costuras', 'Servicios de costura y confección', 'cut');

-- Insertar usuario administrador (role en mayúsculas, solo si no existe)
INSERT INTO users (email, password, role, status, email_verified)
SELECT 'admin@servicefinder.com',
    '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewdBPj89UZoderOi',
    'ADMIN',
    'active',
    TRUE
WHERE NOT EXISTS (SELECT 1 FROM users WHERE email = 'admin@servicefinder.com');

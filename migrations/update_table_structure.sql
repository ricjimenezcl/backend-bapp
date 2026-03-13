-- Agregar nuevas columnas a la tabla service_categories
ALTER TABLE service_categories 
ADD COLUMN parent_category VARCHAR(100),
ADD COLUMN icon VARCHAR(50),
ADD COLUMN is_active BOOLEAN DEFAULT TRUE,
ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;

-- Actualizar la tabla service_providers para usar las nuevas categorías
UPDATE service_providers SET service_category = 'Electricista domiciliario' WHERE service_category = 'electricista';
UPDATE service_providers SET service_category = 'Mecánica automotriz' WHERE service_category = 'mecanico';
UPDATE service_providers SET service_category = 'Vulcanización' WHERE service_category = 'vulcanizacion';
UPDATE service_providers SET service_category = 'Grúa' WHERE service_category = 'gruas';
UPDATE service_providers SET service_category = 'Aseo' WHERE service_category = 'aseo';
UPDATE service_providers SET service_category = 'Jardinería' WHERE service_category = 'jardineria';
UPDATE service_providers SET service_category = 'Costurería y sastrería' WHERE service_category = 'costuras';
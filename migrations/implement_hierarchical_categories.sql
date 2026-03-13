-- 1. Crear tabla de categorías principales
CREATE TABLE IF NOT EXISTS main_categories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    icon VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Insertar categorías principales
INSERT IGNORE INTO main_categories (name, description, icon) VALUES
('Hogar y Construcción', 'Servicios para el hogar y construcción', 'home'),
('Vehículos', 'Servicios para vehículos y automotriz', 'car'),
('Mantenimiento y Limpieza', 'Servicios de mantenimiento y limpieza', 'build'),
('Belleza y Cuidado Personal', 'Servicios de belleza y cuidado personal', 'person'),
('Reparaciones y Tecnología', 'Servicios de reparación y tecnología', 'settings'),
('Mascotas', 'Servicios para mascotas', 'paw'),
('Otros Servicios', 'Otros servicios diversos', 'ellipse');

-- 3. Agregar relación a service_categories
ALTER TABLE service_categories 
ADD COLUMN main_category_id INT,
ADD FOREIGN KEY (main_category_id) REFERENCES main_categories(id);

-- 4. Actualizar las categorías de servicios con sus main_category_id
UPDATE service_categories sc
JOIN main_categories mc ON sc.parent_category = mc.name
SET sc.main_category_id = mc.id;

-- 5. Crear índice para mejor performance
CREATE INDEX idx_service_categories_main_category ON service_categories(main_category_id);

-- 6. Verificar la actualización
SELECT 
    mc.name as main_category,
    COUNT(sc.id) as service_count
FROM main_categories mc
LEFT JOIN service_categories sc ON mc.id = sc.main_category_id
GROUP BY mc.id, mc.name
ORDER BY service_count DESC;
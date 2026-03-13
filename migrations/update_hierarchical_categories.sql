-- Crear tabla de categorías principales si no existe
CREATE TABLE IF NOT EXISTS main_categories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    icon VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insertar categorías principales
INSERT IGNORE INTO main_categories (name, description, icon) VALUES
('Hogar y Construcción', 'Servicios para el hogar y construcción', 'home'),
('Vehículos', 'Servicios para vehículos y automotriz', 'car'),
('Mantenimiento y Limpieza', 'Servicios de mantenimiento y limpieza', 'build'),
('Belleza y Cuidado Personal', 'Servicios de belleza y cuidado personal', 'person'),
('Reparaciones y Tecnología', 'Servicios de reparación y tecnología', 'settings'),
('Mascotas', 'Servicios para mascotas', 'paw'),
('Otros Servicios', 'Otros servicios diversos', 'ellipse');

-- Actualizar tabla service_categories para tener relación con main_categories
ALTER TABLE service_categories 
ADD COLUMN main_category_id INT,
ADD FOREIGN KEY (main_category_id) REFERENCES main_categories(id);

-- Actualizar las categorías existentes con sus main_category_id
UPDATE service_categories sc
JOIN main_categories mc ON sc.parent_category = mc.name
SET sc.main_category_id = mc.id;

-- Crear índice para mejor performance
CREATE INDEX idx_service_categories_main_category ON service_categories(main_category_id);
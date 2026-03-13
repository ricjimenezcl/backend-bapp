-- Consolidado para PostgreSQL: Estructura principal y datos mínimos
-- Ejecutar en una base de datos vacía

-- Usuarios
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password VARCHAR(255),
    role VARCHAR(20) NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    email_verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Perfiles de usuario
CREATE TABLE user_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    full_name VARCHAR(255) NOT NULL,
    phone VARCHAR(20),
    avatar VARCHAR(500),
    bio TEXT,
    rating_avg NUMERIC(3,2) DEFAULT 0.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Proveedores de servicios
CREATE TABLE service_providers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    service_category VARCHAR(100) NOT NULL,
    business_name VARCHAR(255) NOT NULL,
    description TEXT,
    address VARCHAR(500) NOT NULL,
    latitude NUMERIC(10, 8) NOT NULL,
    longitude NUMERIC(11, 8) NOT NULL,
    phone VARCHAR(20) NOT NULL,
    hourly_rate NUMERIC(10, 2),
    is_available BOOLEAN DEFAULT TRUE,
    validation_status VARCHAR(20) DEFAULT 'pending',
    rating_avg NUMERIC(3, 2) DEFAULT 0.0,
    total_reviews INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Reservas
CREATE TABLE bookings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id UUID NOT NULL REFERENCES users(id),
    provider_id UUID NOT NULL REFERENCES service_providers(id),
    service_category VARCHAR(100) NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    location_address VARCHAR(500) NOT NULL,
    location_lat NUMERIC(10, 8),
    location_lng NUMERIC(11, 8),
    scheduled_date TIMESTAMP,
    price NUMERIC(10, 2),
    duration INT,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Pagos
CREATE TABLE payments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    booking_id UUID NOT NULL REFERENCES bookings(id),
    amount NUMERIC(10, 2) NOT NULL,
    payment_method VARCHAR(50) NOT NULL,
    transaction_id VARCHAR(255),
    status VARCHAR(20) DEFAULT 'pending',
    sii_receipt_url VARCHAR(500),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Reseñas
CREATE TABLE reviews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    booking_id UUID NOT NULL REFERENCES bookings(id),
    rating INT NOT NULL CHECK (rating >= 1 AND rating <= 5),
    comment TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Documentos
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    document_type VARCHAR(30) NOT NULL,
    file_url VARCHAR(500) NOT NULL,
    verified BOOLEAN DEFAULT FALSE,
    verified_by UUID,
    verified_at TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Categorías de servicio
CREATE TABLE service_categories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    icon VARCHAR(50)
);

-- Datos mínimos
INSERT INTO service_categories (name, description, icon) VALUES
('electricista', 'Servicios eléctricos residenciales e industriales', 'flash'),
('mecanico', 'Reparación y mantenimiento de vehículos', 'car'),
('vulcanizacion', 'Reparación y cambio de neumáticos', 'build'),
('gruas', 'Servicios de grúa y transporte vehicular', 'trail-sign'),
('aseo', 'Limpieza residencial y comercial', 'home'),
('jardineria', 'Mantenimiento de jardines y áreas verdes', 'leaf'),
('costuras', 'Servicios de costura y confección', 'cut');

-- Usuario administrador
INSERT INTO users (id, email, password, role, status, email_verified) VALUES (
    gen_random_uuid(),
    'admin@servicefinder.com',
    '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewdBPj89UZoderOi',
    'admin',
    'active',
    TRUE
);

-- Crear base de datos si no existe
CREATE DATABASE IF NOT EXISTS service_finder;
USE service_finder;

-- Tabla de usuarios
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    password VARCHAR(255),
    role ENUM('client', 'provider', 'admin') NOT NULL,
    status ENUM('pending', 'active', 'suspended', 'rejected') DEFAULT 'pending',
    email_verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_email (email),
    INDEX idx_role (role),
    INDEX idx_status (status)
);

-- Tabla de perfiles de usuario
CREATE TABLE IF NOT EXISTS user_profiles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    phone VARCHAR(20),
    avatar VARCHAR(500),
    bio TEXT,
    rating_avg DECIMAL(3,2) DEFAULT 0.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user_id (user_id)
);

-- Tabla de proveedores de servicios
CREATE TABLE IF NOT EXISTS service_providers (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    service_category VARCHAR(100) NOT NULL,
    business_name VARCHAR(255) NOT NULL,
    description TEXT,
    address VARCHAR(500) NOT NULL,
    latitude DECIMAL(10, 8) NOT NULL,
    longitude DECIMAL(11, 8) NOT NULL,
    phone VARCHAR(20) NOT NULL,
    hourly_rate DECIMAL(10, 2),
    is_available BOOLEAN DEFAULT TRUE,
    validation_status ENUM('pending', 'approved', 'rejected') DEFAULT 'pending',
    rating_avg DECIMAL(3, 2) DEFAULT 0.0,
    total_reviews INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_category (service_category),
    INDEX idx_location (latitude, longitude),
    INDEX idx_validation (validation_status),
    INDEX idx_availability (is_available)
);

-- Tabla de reservas
CREATE TABLE IF NOT EXISTS bookings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    client_id INT NOT NULL,
    provider_id INT NOT NULL,
    service_category VARCHAR(100) NOT NULL,
    status ENUM('pending', 'confirmed', 'in_progress', 'completed', 'cancelled') DEFAULT 'pending',
    location_address VARCHAR(500) NOT NULL,
    location_lat DECIMAL(10, 8),
    location_lng DECIMAL(11, 8),
    scheduled_date DATETIME,
    price DECIMAL(10, 2),
    duration INT,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (client_id) REFERENCES users(id),
    FOREIGN KEY (provider_id) REFERENCES service_providers(id),
    INDEX idx_client (client_id),
    INDEX idx_provider (provider_id),
    INDEX idx_status (status),
    INDEX idx_date (scheduled_date)
);

-- Tabla de pagos
CREATE TABLE IF NOT EXISTS payments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    booking_id INT NOT NULL,
    amount DECIMAL(10, 2) NOT NULL,
    payment_method VARCHAR(50) NOT NULL,
    transaction_id VARCHAR(255),
    status ENUM('pending', 'completed', 'failed', 'refunded') DEFAULT 'pending',
    sii_receipt_url VARCHAR(500),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (booking_id) REFERENCES bookings(id),
    INDEX idx_booking (booking_id),
    INDEX idx_status (status),
    INDEX idx_transaction (transaction_id)
);

-- Tabla de reseñas
CREATE TABLE IF NOT EXISTS reviews (
    id INT AUTO_INCREMENT PRIMARY KEY,
    booking_id INT NOT NULL,
    rating INT NOT NULL CHECK (rating >= 1 AND rating <= 5),
    comment TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (booking_id) REFERENCES bookings(id),
    INDEX idx_booking (booking_id),
    INDEX idx_rating (rating)
);

-- Tabla de documentos
CREATE TABLE IF NOT EXISTS documents (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    document_type ENUM('cedula_front', 'cedula_back', 'antecedentes', 'other') NOT NULL,
    file_url VARCHAR(500) NOT NULL,
    verified BOOLEAN DEFAULT FALSE,
    verified_by INT,
    verified_at TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    INDEX idx_user (user_id),
    INDEX idx_verified (verified)
);

-- Tabla de categorías de servicio
CREATE TABLE IF NOT EXISTS service_categories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    icon VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insertar categorías de servicio por defecto
INSERT IGNORE INTO service_categories (name, description, icon) VALUES
('electricista', 'Servicios eléctricos residenciales e industriales', 'flash'),
('mecanico', 'Reparación y mantenimiento de vehículos', 'car'),
('vulcanizacion', 'Reparación y cambio de neumáticos', 'build'),
('gruas', 'Servicios de grúa y transporte vehicular', 'trail-sign'),
('aseo', 'Limpieza residencial y comercial', 'home'),
('jardineria', 'Mantenimiento de jardines y áreas verdes', 'leaf'),
('costuras', 'Servicios de costura y confección', 'cut');

-- Crear usuario administrador por defecto (password: admin123)
INSERT IGNORE INTO users (email, password, role, status, email_verified) 
VALUES ('admin@servicefinder.com', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewdBPj89UZoderOi', 'admin', 'active', TRUE);

-- Crear perfil para el administrador
INSERT IGNORE INTO user_profiles (user_id, full_name, phone) 
VALUES (1, 'Administrador', '+56912345678');
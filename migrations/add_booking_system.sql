-- ============================================================================
-- FASE 1C: BOOKING SYSTEM MIGRATION
-- Implementa sistema completo de reservas, pagos y reviews
-- ============================================================================

-- ============================================================================
-- TABLA 1: BOOKINGS (Reservas)
-- ============================================================================
CREATE TABLE IF NOT EXISTS bookings (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    
    -- Información de la reserva
    scheduled_date DATE NOT NULL,
    scheduled_time TIME NOT NULL,
    duration INTEGER NOT NULL CHECK (duration > 0), -- minutos
    description TEXT,
    
    -- Precio
    total_price DECIMAL(10, 2) NOT NULL CHECK (total_price >= 0),
    currency VARCHAR(3) DEFAULT 'CLP',
    
    -- Estado de la reserva
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING' CHECK (status IN (
        'PENDING',      -- Pendiente confirmación del proveedor
        'CONFIRMED',    -- Confirmada
        'IN_PROGRESS',  -- En progreso (started)
        'COMPLETED',    -- Completada
        'CANCELLED',    -- Cancelada
        'NOSHOW'        -- No asistió
    )),
    
    -- Metadatos
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    
    -- Índices para búsquedas rápidas
    CONSTRAINT unique_booking_datetime UNIQUE (provider_id, scheduled_date, scheduled_time),
    FOREIGN KEY (client_id) REFERENCES users(id),
    FOREIGN KEY (provider_id) REFERENCES users(id),
    FOREIGN KEY (service_id) REFERENCES services(id)
);

CREATE INDEX IF NOT EXISTS idx_bookings_client_id ON bookings(client_id);
CREATE INDEX IF NOT EXISTS idx_bookings_provider_id ON bookings(provider_id);
CREATE INDEX IF NOT EXISTS idx_bookings_status ON bookings(status);
CREATE INDEX IF NOT EXISTS idx_bookings_scheduled_date ON bookings(scheduled_date);
CREATE INDEX IF NOT EXISTS idx_bookings_created_at ON bookings(created_at DESC);

-- ============================================================================
-- TABLA 2: BOOKING_STATUS_HISTORY (Historial de cambios de estado)
-- ============================================================================
CREATE TABLE IF NOT EXISTS booking_status_history (
    id SERIAL PRIMARY KEY,
    booking_id INTEGER NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
    
    -- Estado anterior y actual
    previous_status VARCHAR(20),
    new_status VARCHAR(20) NOT NULL,
    
    -- Quién realizó el cambio
    changed_by_id INTEGER NOT NULL REFERENCES users(id) ON DELETE SET NULL,
    
    -- Razón del cambio (especialmente importante en cancelaciones)
    reason VARCHAR(50), -- 'CLIENT_CANCELLED', 'PROVIDER_CANCELLED', 'ADMIN_CANCELLED', 'COMPLETED', 'NOSHOW'
    reason_comment TEXT,
    
    -- Información adicional
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_booking_status_history_booking_id ON booking_status_history(booking_id);
CREATE INDEX IF NOT EXISTS idx_booking_status_history_changed_by_id ON booking_status_history(changed_by_id);
CREATE INDEX IF NOT EXISTS idx_booking_status_history_created_at ON booking_status_history(created_at DESC);

-- ============================================================================
-- TABLA 3: PAYMENTS (Pagos)
-- ============================================================================
CREATE TABLE IF NOT EXISTS payments (
    id SERIAL PRIMARY KEY,
    booking_id INTEGER NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
    
    -- Monto
    amount DECIMAL(10, 2) NOT NULL CHECK (amount > 0),
    currency VARCHAR(3) DEFAULT 'CLP',
    
    -- Método de pago
    payment_method VARCHAR(20) NOT NULL CHECK (payment_method IN (
        'CARD',         -- Tarjeta de crédito/débito
        'TRANSFER',     -- Transferencia bancaria
        'CASH',         -- Efectivo (pago en persona)
        'WALLET'        -- Billetera digital
    )),
    
    -- Referencia de la transacción (Stripe, Mercado Pago, etc)
    transaction_id VARCHAR(255),
    payment_gateway VARCHAR(50), -- 'STRIPE', 'MERCADO_PAGO', 'CASH', etc
    
    -- Estado del pago
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING' CHECK (status IN (
        'PENDING',      -- Pendiente de procesar
        'PROCESSING',   -- En procesamiento
        'COMPLETED',    -- Completado
        'FAILED',       -- Falló
        'REFUNDED'      -- Reembolsado
    )),
    
    -- Metadatos
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP,
    
    -- Información de error
    error_message TEXT,
    
    -- Refund info
    refund_amount DECIMAL(10, 2),
    refund_reason TEXT,
    refunded_at TIMESTAMP
);

CREATE INDEX idx_payments_booking_id ON payments(booking_id);
CREATE INDEX idx_payments_status ON payments(status);
CREATE INDEX idx_payments_created_at ON payments(created_at DESC);
CREATE INDEX idx_payments_transaction_id ON payments(transaction_id);

-- ============================================================================
-- TABLA 4: REVIEWS (Reseñas y calificaciones)
-- ============================================================================
CREATE TABLE IF NOT EXISTS reviews (
    id SERIAL PRIMARY KEY,
    booking_id INTEGER NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
    
    -- Quién reviewea a quién
    reviewer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reviewed_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- Calificación
    rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
    
    -- Comentario
    comment TEXT,
    
    -- Aspetos evaluados
    punctuality_rating INTEGER CHECK (punctuality_rating >= 1 AND punctuality_rating <= 5),
    quality_rating INTEGER CHECK (quality_rating >= 1 AND quality_rating <= 5),
    communication_rating INTEGER CHECK (communication_rating >= 1 AND communication_rating <= 5),
    
    -- Metadatos
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_public BOOLEAN DEFAULT TRUE
);

CREATE INDEX idx_reviews_booking_id ON reviews(booking_id);
CREATE INDEX idx_reviews_reviewer_id ON reviews(reviewer_id);
CREATE INDEX idx_reviews_reviewed_user_id ON reviews(reviewed_user_id);
CREATE INDEX idx_reviews_rating ON reviews(rating);
CREATE INDEX idx_reviews_created_at ON reviews(created_at DESC);

-- ============================================================================
-- TABLA 5: BOOKING_CANCELLATIONS (Detalles de cancelaciones)
-- ============================================================================
CREATE TABLE IF NOT EXISTS booking_cancellations (
    id SERIAL PRIMARY KEY,
    booking_id INTEGER NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
    
    -- Quién canceló
    cancelled_by_id INTEGER NOT NULL REFERENCES users(id) ON DELETE SET NULL,
    
    -- Razón de cancelación
    reason VARCHAR(50) NOT NULL CHECK (reason IN (
        'CLIENT_REQUEST',
        'PROVIDER_REQUEST',
        'ADMIN_REQUEST',
        'PAYMENT_FAILED',
        'PROVIDER_UNAVAILABLE',
        'CLIENT_NO_SHOW',
        'OTHER'
    )),
    reason_comment TEXT,
    
    -- Reembolso
    refund_percentage INTEGER DEFAULT 100 CHECK (refund_percentage >= 0 AND refund_percentage <= 100),
    refund_amount DECIMAL(10, 2),
    
    -- Metadatos
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP
);

CREATE INDEX idx_booking_cancellations_booking_id ON booking_cancellations(booking_id);
CREATE INDEX idx_booking_cancellations_cancelled_by_id ON booking_cancellations(cancelled_by_id);
CREATE INDEX idx_booking_cancellations_created_at ON booking_cancellations(created_at DESC);
-- ============================================================================
-- VERIFICAR ESTRUCTURA DE BOOKINGS Y AGREGAR CAMPOS FALTANTES
-- ============================================================================

-- Agregar service_id si no existe (en lugar de service_category)
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS service_id INTEGER REFERENCES services(id);

-- Agregar scheduled_time si no existe
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS scheduled_time TIME;

-- Agregar total_price si no existe (parece que tienes price, pero la vista espera total_price)
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS total_price DECIMAL(10,2);

-- Agregar completed_at si no existe
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP;

-- Agregar campos de rating si no existen en reviews
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS is_public BOOLEAN DEFAULT TRUE;
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS punctuality_rating INTEGER;
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS quality_rating INTEGER;
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS communication_rating INTEGER;

-- Si total_price no existe pero price sí, copiar los valores
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns 
               WHERE table_name = 'bookings' AND column_name = 'price') 
       AND EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'bookings' AND column_name = 'total_price') THEN
        UPDATE bookings SET total_price = price WHERE total_price IS NULL AND price IS NOT NULL;
    END IF;
END $$;

-- ============================================================================
-- TABLA 6: SERVICE_AVAILABILITY (Disponibilidad de proveedores)
-- ============================================================================
CREATE TABLE IF NOT EXISTS service_availability (
    id SERIAL PRIMARY KEY,
    provider_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    
    -- Disponibilidad por día de la semana
    day_of_week INTEGER NOT NULL CHECK (day_of_week >= 0 AND day_of_week <= 6), -- 0=Lunes, 6=Domingo
    
    -- Horarios
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    
    -- Información
    is_available BOOLEAN DEFAULT TRUE,
    timezone VARCHAR(50) DEFAULT 'America/Santiago',
    
    -- Metadatos
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT unique_availability UNIQUE (provider_id, service_id, day_of_week)
);

CREATE INDEX IF NOT EXISTS idx_service_availability_provider_id ON service_availability(provider_id);
CREATE INDEX IF NOT EXISTS idx_service_availability_service_id ON service_availability(service_id);
CREATE INDEX IF NOT EXISTS idx_service_availability_day_of_week ON service_availability(day_of_week);

-- ============================================================================
-- TABLA ADICIONAL: BOOKING_NOTES (Notas internas)
-- ============================================================================
CREATE TABLE IF NOT EXISTS booking_notes (
    id SERIAL PRIMARY KEY,
    booking_id INTEGER NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
    
    -- Nota
    note_type VARCHAR(20) CHECK (note_type IN ('INTERNAL', 'CLIENT_VISIBLE', 'PROVIDER_VISIBLE')),
    content TEXT NOT NULL,
    
    -- Quién escribió
    created_by_id INTEGER NOT NULL REFERENCES users(id) ON DELETE SET NULL,
    
    -- Metadatos
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_booking_notes_booking_id ON booking_notes(booking_id);

-- ============================================================================
-- TRIGGERS: Actualizar updated_at automáticamente
-- ============================================================================

-- Función para actualizar updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- VIEWS ÚTILES
-- ============================================================================

-- Vista: Bookings con información del cliente y proveedor
-- AJUSTADA a la estructura real de bookings
CREATE OR REPLACE VIEW booking_details AS
SELECT 
    b.id,
    b.client_id,
    c.email as client_email,
    -- Obtener nombre del perfil del cliente
    COALESCE(cp.full_name, c.email) as client_name,
    b.provider_id,
    p.email as provider_email,
    -- Obtener nombre del perfil del proveedor
    COALESCE(pp.full_name, p.email) as provider_name,
    b.service_id,
    s.name as service_name,
    b.scheduled_date,
    b.scheduled_time,
    b.duration,
    COALESCE(b.total_price, b.price) as total_price,  -- Usar total_price o price
    b.status,
    b.created_at,
    b.completed_at,
    -- Campos adicionales que tienes en bookings
    b.service_category,
    b.location_address,
    b.location_lat,
    b.location_lng,
    b.description
FROM bookings b
JOIN users c ON b.client_id = c.id
JOIN users p ON b.provider_id = p.id
LEFT JOIN user_profiles cp ON c.id = cp.user_id
LEFT JOIN user_profiles pp ON p.id = pp.user_id
LEFT JOIN services s ON b.service_id = s.id;

-- Vista: Promedio de ratings por usuario
-- AJUSTADA para usar provider_id (asumiendo que se califica al proveedor)
CREATE OR REPLACE VIEW user_ratings AS
SELECT 
    r.provider_id as user_id,  -- Usar provider_id en lugar de reviewed_user_id
    COUNT(*) as total_reviews,
    ROUND(AVG(r.rating), 2) as avg_rating,
    ROUND(AVG(COALESCE(r.punctuality_rating, r.rating)), 2) as avg_punctuality,
    ROUND(AVG(COALESCE(r.quality_rating, r.rating)), 2) as avg_quality,
    ROUND(AVG(COALESCE(r.communication_rating, r.rating)), 2) as avg_communication
FROM reviews r
WHERE COALESCE(r.is_public, TRUE) = TRUE  -- Si no existe is_public, asumir TRUE
GROUP BY r.provider_id;

-- Vista alternativa si también quieres incluir ratings de clientes
-- CREATE OR REPLACE VIEW user_ratings_complete AS
-- SELECT 
--     user_id,
--     total_reviews,
--     avg_rating,
--     avg_punctuality,
--     avg_quality,
--     avg_communication
-- FROM (
--     -- Ratings como proveedor
--     SELECT 
--         r.provider_id as user_id,
--         COUNT(*) as total_reviews,
--         ROUND(AVG(r.rating), 2) as avg_rating,
--         ROUND(AVG(COALESCE(r.punctuality_rating, r.rating)), 2) as avg_punctuality,
--         ROUND(AVG(COALESCE(r.quality_rating, r.rating)), 2) as avg_quality,
--         ROUND(AVG(COALESCE(r.communication_rating, r.rating)), 2) as avg_communication
--     FROM reviews r
--     WHERE COALESCE(r.is_public, TRUE) = TRUE
--     GROUP BY r.provider_id
--     
--     UNION ALL
--     
--     -- Ratings como cliente (si tuvieras esa información)
--     SELECT 
--         r.client_id as user_id,
--         COUNT(*) as total_reviews,
--         ROUND(AVG(r.rating), 2) as avg_rating,
--         ROUND(AVG(COALESCE(r.punctuality_rating, r.rating)), 2) as avg_punctuality,
--         ROUND(AVG(COALESCE(r.quality_rating, r.rating)), 2) as avg_quality,
--         ROUND(AVG(COALESCE(r.communication_rating, r.rating)), 2) as avg_communication
--     FROM reviews r
--     WHERE COALESCE(r.is_public, TRUE) = TRUE
--     GROUP BY r.client_id
-- ) all_ratings;

-- ============================================================================
-- AGREGAR COLUMNAS UPDATED_AT SI NO EXISTEN
-- ============================================================================
DO $$
BEGIN
    -- Agregar updated_at a payments si no existe
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'payments' AND column_name = 'updated_at') THEN
        ALTER TABLE payments ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
    END IF;
    
    -- Agregar updated_at a reviews si no existe
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'reviews' AND column_name = 'updated_at') THEN
        ALTER TABLE reviews ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
    END IF;
END $$;

-- ============================================================================
-- CREAR TRIGGERS
-- ============================================================================

-- Eliminar triggers si ya existen para evitar errores
DROP TRIGGER IF EXISTS trigger_update_bookings_updated_at ON bookings;
DROP TRIGGER IF EXISTS trigger_update_payments_updated_at ON payments;
DROP TRIGGER IF EXISTS trigger_update_reviews_updated_at ON reviews;
DROP TRIGGER IF EXISTS trigger_update_service_availability_updated_at ON service_availability;

-- Crear triggers
CREATE TRIGGER trigger_update_bookings_updated_at
BEFORE UPDATE ON bookings
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trigger_update_payments_updated_at
BEFORE UPDATE ON payments
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trigger_update_reviews_updated_at
BEFORE UPDATE ON reviews
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trigger_update_service_availability_updated_at
BEFORE UPDATE ON service_availability
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

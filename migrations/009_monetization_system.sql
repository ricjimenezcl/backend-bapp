-- ============================================
-- MIGRACIÓN 009: Sistema de Monetización Multiplataforma
-- Fecha: 2026-03-09
-- Descripción: Sistema completo de pagos para Android, iOS y Web
-- ============================================

-- ============================================
-- TABLA: products (Catálogo de productos)
-- ============================================
CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    sku VARCHAR(100) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    target_role VARCHAR(20) NOT NULL CHECK (target_role IN ('CLIENT', 'PROVIDER', 'ALL')),
    duration_days INTEGER NOT NULL,
    price_usd DECIMAL(10, 2) NOT NULL,
    price_clp DECIMAL(10, 2) NOT NULL,
    free_limit INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Índices para products
CREATE INDEX IF NOT EXISTS idx_products_sku ON products(sku);
CREATE INDEX IF NOT EXISTS idx_products_target_role ON products(target_role);
CREATE INDEX IF NOT EXISTS idx_products_is_active ON products(is_active);

-- ============================================
-- TABLA: platform_products (Mapeo multiplataforma)
-- ============================================
CREATE TABLE IF NOT EXISTS platform_products (
    id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    platform VARCHAR(20) NOT NULL CHECK (platform IN ('google_play', 'apple_iap', 'web')),
    platform_product_id VARCHAR(255) NOT NULL,
    platform_price VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_product_platform UNIQUE(product_id, platform)
);

-- Índices para platform_products
CREATE INDEX IF NOT EXISTS idx_platform_products_platform ON platform_products(platform);
CREATE INDEX IF NOT EXISTS idx_platform_products_product_id ON platform_products(product_id);
CREATE INDEX IF NOT EXISTS idx_platform_products_platform_product_id ON platform_products(platform_product_id);

-- ============================================
-- TABLA: transactions (Historial completo de pagos)
-- ============================================
CREATE TABLE IF NOT EXISTS transactions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    product_id INTEGER REFERENCES products(id),
    platform VARCHAR(20) NOT NULL CHECK (platform IN ('google_play', 'apple_iap', 'web')),
    amount DECIMAL(10, 2) NOT NULL,
    currency VARCHAR(3) DEFAULT 'CLP',
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'completed', 'failed', 'refunded', 'expired')),
    
    -- IDs de transacción por plataforma
    transaction_id VARCHAR(255),
    platform_transaction_id VARCHAR(255),
    platform_order_id VARCHAR(255),
    
    -- Validación de compra
    purchase_token TEXT,
    receipt_data TEXT,
    validated_at TIMESTAMP,
    validation_response TEXT,
    
    -- Metadata de seguridad
    ip_address VARCHAR(50),
    user_agent TEXT,
    device_info JSONB,
    
    -- Activación del beneficio
    activated_at TIMESTAMP,
    expires_at TIMESTAMP,
    benefit_metadata JSONB,
    
    -- Auditoría
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    refunded_at TIMESTAMP,
    refund_reason TEXT
);

-- Índices para transactions
CREATE INDEX IF NOT EXISTS idx_transactions_user_id ON transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_transactions_status ON transactions(status);
CREATE INDEX IF NOT EXISTS idx_transactions_platform ON transactions(platform);
CREATE INDEX IF NOT EXISTS idx_transactions_transaction_id ON transactions(transaction_id);
CREATE INDEX IF NOT EXISTS idx_transactions_platform_transaction_id ON transactions(platform_transaction_id);
CREATE INDEX IF NOT EXISTS idx_transactions_created_at ON transactions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_transactions_expires_at ON transactions(expires_at) WHERE status = 'completed';
CREATE INDEX IF NOT EXISTS idx_transactions_user_status ON transactions(user_id, status);

-- ============================================
-- TABLA: provider_service_slots (Slots de servicios)
-- ============================================
CREATE TABLE IF NOT EXISTS provider_service_slots (
    id SERIAL PRIMARY KEY,
    provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
    slot_number INTEGER NOT NULL CHECK (slot_number > 0),
    is_free BOOLEAN DEFAULT TRUE NOT NULL,
    service_provider_id INTEGER REFERENCES service_providers(id) ON DELETE SET NULL,
    transaction_id INTEGER REFERENCES transactions(id),
    
    -- Control de vigencia
    activated_at TIMESTAMP,
    expires_at TIMESTAMP,
    is_active BOOLEAN DEFAULT FALSE NOT NULL,
    
    -- Auditoría
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT uq_provider_slot_number UNIQUE(provider_id, slot_number)
);

-- Índices para provider_service_slots
CREATE INDEX IF NOT EXISTS idx_provider_service_slots_provider_id ON provider_service_slots(provider_id);
CREATE INDEX IF NOT EXISTS idx_provider_service_slots_expires_at ON provider_service_slots(expires_at) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_provider_service_slots_is_active ON provider_service_slots(is_active);
CREATE INDEX IF NOT EXISTS idx_provider_service_slots_service_provider_id ON provider_service_slots(service_provider_id);

-- ============================================
-- DATOS INICIALES: products
-- ============================================
INSERT INTO products (sku, name, description, target_role, duration_days, price_usd, price_clp, free_limit, metadata) VALUES
(
    'premium_access_7days',
    'Acceso Premium 7 días',
    'Interactúa con todos los proveedores sin límites por 7 días',
    'CLIENT',
    7,
    1.64,
    1490,
    0,
    '{"benefits": ["Acceso ilimitado a todos los proveedores", "Chat con cualquier proveedor", "Reservas sin restricciones", "Soporte prioritario"]}'::jsonb
),
(
    'service_publication_30days',
    'Publicación de Servicio Adicional',
    'Publica un servicio adicional por 30 días',
    'PROVIDER',
    30,
    3.29,
    2990,
    2,
    '{"benefits": ["Publica hasta 3 servicios simultáneos", "Vigencia de 30 días", "Mayor visibilidad en búsquedas", "Estadísticas detalladas"]}'::jsonb
)
ON CONFLICT (sku) DO NOTHING;

-- ============================================
-- DATOS INICIALES: platform_products
-- ============================================
INSERT INTO platform_products (product_id, platform, platform_product_id, platform_price) VALUES
-- Premium Access - Android
((SELECT id FROM products WHERE sku = 'premium_access_7days'), 'google_play', 'io.ionic.bappsearch.premium_7days', '1.64'),
-- Premium Access - iOS
((SELECT id FROM products WHERE sku = 'premium_access_7days'), 'apple_iap', 'premium_access_7days', '1.64'),
-- Premium Access - Web
((SELECT id FROM products WHERE sku = 'premium_access_7days'), 'web', 'premium_access_7days_web', '1490'),

-- Service Publication - Android
((SELECT id FROM products WHERE sku = 'service_publication_30days'), 'google_play', 'io.ionic.bappsearch.service_slot_30days', '3.29'),
-- Service Publication - iOS
((SELECT id FROM products WHERE sku = 'service_publication_30days'), 'apple_iap', 'service_publication_30days', '3.29'),
-- Service Publication - Web
((SELECT id FROM products WHERE sku = 'service_publication_30days'), 'web', 'service_publication_30days_web', '2990')
ON CONFLICT (product_id, platform) DO NOTHING;

-- ============================================
-- FUNCIÓN: Inicializar slots gratuitos para proveedores
-- ============================================
CREATE OR REPLACE FUNCTION initialize_provider_free_slots()
RETURNS TRIGGER AS $$
BEGIN
    -- Crear 2 slots gratuitos para cada proveedor nuevo
    INSERT INTO provider_service_slots (provider_id, slot_number, is_free, is_active)
    VALUES 
        (NEW.id, 1, TRUE, TRUE),
        (NEW.id, 2, TRUE, TRUE);
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================
-- TRIGGER: Auto-crear slots gratuitos al registrar proveedor
-- ============================================
DROP TRIGGER IF EXISTS trigger_initialize_provider_slots ON providers;
CREATE TRIGGER trigger_initialize_provider_slots
    AFTER INSERT ON providers
    FOR EACH ROW
    EXECUTE FUNCTION initialize_provider_free_slots();

-- ============================================
-- FUNCIÓN: Actualizar updated_at automáticamente
-- ============================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Aplicar trigger de updated_at a todas las tablas nuevas
DROP TRIGGER IF EXISTS update_products_updated_at ON products;
CREATE TRIGGER update_products_updated_at
    BEFORE UPDATE ON products
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_transactions_updated_at ON transactions;
CREATE TRIGGER update_transactions_updated_at
    BEFORE UPDATE ON transactions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_provider_service_slots_updated_at ON provider_service_slots;
CREATE TRIGGER update_provider_service_slots_updated_at
    BEFORE UPDATE ON provider_service_slots
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================
-- COMENTARIOS EN TABLAS
-- ============================================
COMMENT ON TABLE products IS 'Catálogo de productos monetizables del sistema';
COMMENT ON TABLE platform_products IS 'Mapeo de productos a SKUs específicos de cada plataforma (Google Play, Apple IAP, Web)';
COMMENT ON TABLE transactions IS 'Historial completo de transacciones con validación de pagos por plataforma';
COMMENT ON TABLE provider_service_slots IS 'Gestión de slots de servicios para proveedores (2 gratis, resto pagos)';

COMMENT ON COLUMN products.sku IS 'Identificador único del producto (ej: premium_access_7days)';
COMMENT ON COLUMN products.target_role IS 'Rol objetivo: CLIENT, PROVIDER o ALL';
COMMENT ON COLUMN products.free_limit IS 'Límite gratuito para proveedores (ej: 2 servicios gratis)';

COMMENT ON COLUMN transactions.platform IS 'Plataforma de pago: google_play, apple_iap, web';
COMMENT ON COLUMN transactions.purchase_token IS 'Token de compra de Google Play o Apple para validación';
COMMENT ON COLUMN transactions.receipt_data IS 'Receipt completo serializado (JSON)';

COMMENT ON COLUMN provider_service_slots.is_free IS 'TRUE para slots 1 y 2 (gratuitos), FALSE para slots pagos';
COMMENT ON COLUMN provider_service_slots.slot_number IS 'Número de slot (1, 2, 3, etc.)';

-- ============================================
-- VERIFICACIÓN FINAL
-- ============================================
DO $$
BEGIN
    RAISE NOTICE '✅ Migración 009 completada exitosamente';
    RAISE NOTICE '   - Tabla products creada con % productos', (SELECT COUNT(*) FROM products);
    RAISE NOTICE '   - Tabla platform_products creada con % mapeos', (SELECT COUNT(*) FROM platform_products);
    RAISE NOTICE '   - Tabla transactions creada';
    RAISE NOTICE '   - Tabla provider_service_slots creada';
    RAISE NOTICE '   - Triggers configurados para auto-inicialización de slots';
END $$;

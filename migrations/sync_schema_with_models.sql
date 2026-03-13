-- ============================================================================
-- SCRIPT COMPLETO: Sincronizar todas las columnas faltantes
-- Fecha: 2026-02-01
-- Descripción: Agrega todas las columnas que definen los modelos SQLAlchemy
-- pero que no existen en la DB
-- ============================================================================

-- ============================================================================
-- 1. TABLA: providers - Columnas de validación biométrica
-- ============================================================================
ALTER TABLE providers
ADD COLUMN IF NOT EXISTS selfie_url VARCHAR(500) NULL,
ADD COLUMN IF NOT EXISTS validation_status VARCHAR(50) DEFAULT 'pending' NULL,
ADD COLUMN IF NOT EXISTS validation_notes TEXT NULL;

-- ============================================================================
-- 2. TABLA: bookings - Columna currency
-- ============================================================================
ALTER TABLE bookings
ADD COLUMN IF NOT EXISTS currency VARCHAR(3) DEFAULT 'CLP' NULL;

-- ============================================================================
-- 3. TABLA: users - Campos de reset de contraseña (si faltan)
-- ============================================================================
ALTER TABLE users
ADD COLUMN IF NOT EXISTS reset_token VARCHAR(128) NULL,
ADD COLUMN IF NOT EXISTS reset_token_expiration TIMESTAMP NULL;

-- ============================================================================
-- 4. TABLA: user_profiles - Campos adicionales
-- ============================================================================
ALTER TABLE user_profiles
ADD COLUMN IF NOT EXISTS bio TEXT NULL;

-- ============================================================================
-- 5. Validar que todas las columnas se agregaron
-- ============================================================================
-- Ejecutar después de aplicar la migración:
-- SELECT column_name, data_type FROM information_schema.columns 
-- WHERE table_name IN ('providers', 'bookings', 'users', 'user_profiles')
-- ORDER BY table_name, column_name;

-- Migración: Agregar columnas faltantes a tabla providers
-- Fecha: 2026-02-01

-- Agregar columna selfie_url si no existe
ALTER TABLE providers
ADD COLUMN IF NOT EXISTS selfie_url VARCHAR(500) NULL;

-- Validar que la columna se agregó correctamente
-- SELECT column_name FROM information_schema.columns 
-- WHERE table_name='providers' AND column_name='selfie_url';

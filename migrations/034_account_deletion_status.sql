-- Migración: soporte para eliminación de cuenta (requisito Google Play / App Store)
-- Agrega el valor 'DELETED' al enum user_status y una columna deleted_at.
--
-- IMPORTANTE: ALTER TYPE ... ADD VALUE no puede ejecutarse dentro del mismo
-- bloque de transacción que luego USA ese valor. Ejecutar este archivo tal
-- cual (statement por statement, sin envolver en una transacción manual
-- adicional) via psql:
--   psql "$DATABASE_URL" -f migrations/034_account_deletion_status.sql

ALTER TYPE user_status ADD VALUE IF NOT EXISTS 'DELETED';

ALTER TABLE users ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP NULL;

-- Agrega campos para recuperación de contraseña
ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_token VARCHAR(128);
ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_token_expiration TIMESTAMP;

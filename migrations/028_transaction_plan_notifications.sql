-- Migración 028: tracking de notificaciones de ciclo de vida de plan (transactions)
-- Agrega columnas para evitar reenvíos duplicados de los avisos de:
--   - activación/inicio de plan
--   - recordatorio de renovación (próximo a vencer)
--   - término/expiración de plan
ALTER TABLE transactions
    ADD COLUMN IF NOT EXISTS activation_notified_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS renewal_reminder_sent_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS expiration_notified_at TIMESTAMP;

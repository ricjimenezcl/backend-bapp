-- Migración 028: tracking de notificaciones de ciclo de vida de plan (transactions)
-- Agrega columnas para evitar reenvíos duplicados de los avisos de:
--   - activación/inicio de plan
--   - recordatorio de renovación (próximo a vencer)
--   - término/expiración de plan
ALTER TABLE transactions
    ADD COLUMN IF NOT EXISTS activation_notified_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS renewal_reminder_sent_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS expiration_notified_at TIMESTAMP;

-- Backfill: marcar como "ya notificado" todo lo que es histórico (activado o
-- expirado ANTES de existir esta feature), para que el cron NO le mande un
-- aluvión de correos "tu plan está activo"/"tu plan terminó" a transacciones
-- viejas la primera vez que corra. El aviso de renovación (ventana de 5 días
-- hacia adelante) no necesita backfill: por diseño solo mira hacia el futuro.
UPDATE transactions
SET activation_notified_at = activated_at
WHERE status = 'completed'
  AND activated_at IS NOT NULL
  AND activation_notified_at IS NULL;

UPDATE transactions
SET expiration_notified_at = NOW()
WHERE status = 'completed'
  AND expires_at IS NOT NULL
  AND expires_at <= NOW()
  AND expiration_notified_at IS NULL;

-- Índices parciales: el cron solo consulta filas "pendientes" (columna
-- *_notified_at IS NULL), que son una fracción mínima y decreciente de la
-- tabla con el tiempo. Un índice parcial sobre ese subconjunto mantiene la
-- query rápida sin importar cuánto crezca `transactions` en general.
CREATE INDEX IF NOT EXISTS idx_tx_pending_activation_notice
    ON transactions (status)
    WHERE activation_notified_at IS NULL AND activated_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_tx_pending_renewal_notice
    ON transactions (status, expires_at)
    WHERE renewal_reminder_sent_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_tx_pending_expiration_notice
    ON transactions (status, expires_at)
    WHERE expiration_notified_at IS NULL;


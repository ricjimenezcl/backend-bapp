-- ============================================
-- MIGRACIÓN 019: Tracking de notificaciones de provider_service_slots
-- Fecha: 2026-07-14
-- Agrega columnas para evitar reenvíos duplicados de:
--   - Email de activación (al reclamar un slot pagado para un servicio nuevo)
--   - Email de recordatorio de vencimiento (5 días antes de expires_at)
-- ============================================

ALTER TABLE provider_service_slots
    ADD COLUMN IF NOT EXISTS activation_email_sent_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS expiry_reminder_sent_at TIMESTAMP;

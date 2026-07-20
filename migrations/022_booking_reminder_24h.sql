-- 022_booking_reminder_24h.sql
-- Agrega marca para evitar recordatorios 24h duplicados por reserva.

ALTER TABLE bookings
ADD COLUMN IF NOT EXISTS reminder_24h_sent_at TIMESTAMP NULL;

CREATE INDEX IF NOT EXISTS idx_bookings_reminder_24h_sent_at
ON bookings (reminder_24h_sent_at);

-- Migration 006: Partial index para slots disponibles
-- Mejora el rendimiento de la query de slots en get_available_slots endpoint.
--
-- La query filtra bookings con status IN ('PENDING','CONFIRMED') para detectar
-- qué slots están ocupados. Un índice parcial solo indexa esas filas activas,
-- que son minoría del total — mucho más pequeño y rápido que un índice completo.
--
-- Aplica también un índice compuesto para cubrir la join de provider_id + scheduled_date.

-- Índice parcial: solo reservas activas (PENDING o CONFIRMED)
-- Cubre: WHERE provider_id = $1 AND scheduled_date = $2 AND status IN ('PENDING','CONFIRMED')
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_bookings_slots_active
    ON bookings (provider_id, scheduled_date)
    WHERE status IN ('PENDING', 'CONFIRMED');

-- Índice de soporte para invalidación por service_provider_id (slots por servicio específico)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_bookings_service_provider_date
    ON bookings (service_provider_id, scheduled_date)
    WHERE status IN ('PENDING', 'CONFIRMED');

-- Índice de soporte para cancelaciones/completados (para queries de historial)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_bookings_client_status
    ON bookings (client_id, status, created_at DESC);

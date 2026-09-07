-- ============================================================================
-- Fix: bookings.service_id apuntaba a service_categories.id (tabla legacy,
-- desactualizada tras la migración de taxonomía), pero el backend/frontend
-- ya envían valores de services.id (nueva taxonomía) al crear una reserva.
--
-- Error real en producción (Render logs, 2026-09-07):
--   asyncpg.exceptions.ForeignKeyViolationError: insert or update on table
--   "bookings" violates foreign key constraint "bookings_service_id_fkey"
--   DETAIL: Key (service_id)=(348) is not present in table "service_categories".
--
-- Esto bloqueaba TODA creación de reservas para servicios de la taxonomía
-- nueva (prácticamente todo el catálogo actual).
--
-- Este script repunta el FK a services.id, igual que ya se confirmó y
-- corrigió para service_providers.service_id.
-- ============================================================================

-- 1. Diagnóstico (ejecutar y revisar ANTES de aplicar el resto): filas de
--    bookings cuyo service_id no existe en services. Estas quedarán con un
--    valor "huérfano" respecto al nuevo FK (no se valida retroactivamente
--    porque el ALTER de abajo usa NOT VALID), pero conviene saber cuántas hay.
SELECT COUNT(*) AS bookings_con_service_id_huerfano
FROM bookings b
WHERE b.service_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM services s WHERE s.id = b.service_id);

BEGIN;

-- 2. Eliminar el FK viejo (apuntaba a service_categories.id)
ALTER TABLE bookings
    DROP CONSTRAINT IF EXISTS bookings_service_id_fkey;

-- 3. Crear el FK nuevo apuntando a services.id.
--    NOT VALID: no revalida filas existentes (evita fallar por reservas
--    antiguas creadas bajo la taxonomía legacy), pero SÍ se aplica a partir
--    de ahora para todo INSERT/UPDATE nuevo.
ALTER TABLE bookings
    ADD CONSTRAINT bookings_service_id_fkey
    FOREIGN KEY (service_id) REFERENCES services(id)
    NOT VALID;

COMMIT;

-- 4. (Opcional, solo si el diagnóstico del paso 1 dio 0 filas huérfanas)
--    Validar el constraint para que quede completamente verificado:
-- ALTER TABLE bookings VALIDATE CONSTRAINT bookings_service_id_fkey;

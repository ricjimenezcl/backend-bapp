-- ============================================================================
-- Migración 018: Normalización de estados de reservas
-- Fecha: 2026-06-03
-- Descripción:
--   Unifica el modelo de estados al nuevo esquema de 4 estados:
--     PENDING → APPROVED → COMPLETED
--                        ↘ REJECTED
--
--   Transformaciones sobre datos existentes:
--     CONFIRMED   → APPROVED       (el proveedor ya aceptó)
--     IN_PROGRESS → APPROVED       (servicio en curso = aprobado y activo)
--     CANCELLED   (razón PROVIDER_REQUEST) → filas eliminadas + registro en log
--     CANCELLED   (otras razones)  → sin cambio (son cancelaciones del cliente)
--     NOSHOW      → sin cambio     (dato histórico)
--
--   Aplica también en booking_status_history para coherencia de auditoría.
-- ============================================================================

BEGIN;

-- ── 0. Tabla de log de la migración ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS migration_log (
    id          SERIAL PRIMARY KEY,
    migration   VARCHAR(100) NOT NULL,
    action      VARCHAR(100) NOT NULL,
    affected    INTEGER DEFAULT 0,
    details     TEXT,
    executed_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── 1. CONFIRMED → APPROVED ──────────────────────────────────────────────────
DO $$
DECLARE affected INTEGER;
BEGIN
    UPDATE bookings SET status = 'APPROVED' WHERE status = 'CONFIRMED';
    GET DIAGNOSTICS affected = ROW_COUNT;
    INSERT INTO migration_log(migration, action, affected)
    VALUES ('018_normalize_booking_statuses', 'CONFIRMED → APPROVED', affected);
END $$;

-- Historial: normalizar referencias a CONFIRMED
DO $$
DECLARE affected INTEGER;
BEGIN
    UPDATE booking_status_history
    SET new_status = 'APPROVED'
    WHERE new_status = 'CONFIRMED';
    GET DIAGNOSTICS affected = ROW_COUNT;
    INSERT INTO migration_log(migration, action, affected)
    VALUES ('018_normalize_booking_statuses', 'history: new_status CONFIRMED → APPROVED', affected);

    UPDATE booking_status_history
    SET previous_status = 'APPROVED'
    WHERE previous_status = 'CONFIRMED';
    GET DIAGNOSTICS affected = ROW_COUNT;
    INSERT INTO migration_log(migration, action, affected)
    VALUES ('018_normalize_booking_statuses', 'history: previous_status CONFIRMED → APPROVED', affected);
END $$;

-- ── 2. IN_PROGRESS → APPROVED ────────────────────────────────────────────────
DO $$
DECLARE affected INTEGER;
BEGIN
    UPDATE bookings SET status = 'APPROVED' WHERE status = 'IN_PROGRESS';
    GET DIAGNOSTICS affected = ROW_COUNT;
    INSERT INTO migration_log(migration, action, affected)
    VALUES ('018_normalize_booking_statuses', 'IN_PROGRESS → APPROVED', affected);
END $$;

DO $$
DECLARE affected INTEGER;
BEGIN
    UPDATE booking_status_history
    SET new_status = 'APPROVED'
    WHERE new_status = 'IN_PROGRESS';
    GET DIAGNOSTICS affected = ROW_COUNT;
    INSERT INTO migration_log(migration, action, affected)
    VALUES ('018_normalize_booking_statuses', 'history: new_status IN_PROGRESS → APPROVED', affected);

    UPDATE booking_status_history
    SET previous_status = 'APPROVED'
    WHERE previous_status = 'IN_PROGRESS';
    GET DIAGNOSTICS affected = ROW_COUNT;
    INSERT INTO migration_log(migration, action, affected)
    VALUES ('018_normalize_booking_statuses', 'history: previous_status IN_PROGRESS → APPROVED', affected);
END $$;

-- ── 3. CANCELLED (razón PROVIDER_REQUEST) → REJECTED + DELETE ────────────────
-- Las cancelaciones iniciadas por el proveedor equivalen al nuevo estado REJECTED.
-- El nuevo flujo elimina el registro en BD al rechazar, pero para preservar
-- el historial de auditoría creamos un registro en booking_status_history antes
-- de borrar la reserva.

DO $$
DECLARE
    rec             RECORD;
    cancellation    RECORD;
    affected        INTEGER := 0;
BEGIN
    FOR rec IN
        SELECT b.id AS booking_id, b.client_id, b.provider_id
        FROM   bookings b
        JOIN   booking_cancellations bc ON bc.booking_id = b.id
        WHERE  b.status = 'CANCELLED'
        AND    bc.reason = 'PROVIDER_REQUEST'
    LOOP
        -- Registrar en historial antes de borrar
        SELECT * INTO cancellation
        FROM   booking_cancellations
        WHERE  booking_id = rec.booking_id;

        INSERT INTO booking_status_history
            (booking_id, previous_status, new_status, changed_by_id, reason, reason_comment, created_at)
        VALUES
            (rec.booking_id, 'CANCELLED', 'REJECTED',
             cancellation.cancelled_by_id,
             'PROVIDER_REQUEST',
             COALESCE(cancellation.reason_comment, 'Migración automática: CANCELLED(PROVIDER) → REJECTED'),
             NOW());

        -- Eliminar cascada (booking_cancellations, booking_status_history anterior, etc.)
        DELETE FROM bookings WHERE id = rec.booking_id;

        affected := affected + 1;
    END LOOP;

    INSERT INTO migration_log(migration, action, affected)
    VALUES ('018_normalize_booking_statuses',
            'CANCELLED(PROVIDER_REQUEST) → deleted + REJECTED history', affected);
END $$;

-- ── 4. Verificación final ─────────────────────────────────────────────────────
SELECT
    status,
    COUNT(*) AS total
FROM bookings
GROUP BY status
ORDER BY status;

-- Ver log de esta migración
SELECT action, affected, executed_at
FROM migration_log
WHERE migration = '018_normalize_booking_statuses'
ORDER BY id;

COMMIT;

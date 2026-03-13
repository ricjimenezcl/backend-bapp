-- Migración: Convertir ENUM booking_status a VARCHAR

-- 1. Renombrar columna status
ALTER TABLE bookings RENAME COLUMN status TO status_old;

-- 2. Crear nueva columna con VARCHAR
ALTER TABLE bookings ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'PENDING';

-- 3. Copiar datos (convertir enum a varchar)
UPDATE bookings SET status = status_old::text;

-- 4. Dropear columna vieja
ALTER TABLE bookings DROP COLUMN status_old;

-- 5. Booking status history - previous_status
ALTER TABLE booking_status_history RENAME COLUMN previous_status TO previous_status_old;
ALTER TABLE booking_status_history ADD COLUMN previous_status VARCHAR(20);
UPDATE booking_status_history SET previous_status = previous_status_old::text WHERE previous_status_old IS NOT NULL;
ALTER TABLE booking_status_history DROP COLUMN previous_status_old;

-- 6. Booking status history - new_status
ALTER TABLE booking_status_history RENAME COLUMN new_status TO new_status_old;
ALTER TABLE booking_status_history ADD COLUMN new_status VARCHAR(20) NOT NULL;
UPDATE booking_status_history SET new_status = new_status_old::text;
ALTER TABLE booking_status_history DROP COLUMN new_status_old;

-- 7. Drop el tipo ENUM
DROP TYPE IF EXISTS booking_status CASCADE;

-- Verificación
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'bookings' 
AND column_name IN ('status')
ORDER BY ordinal_position;

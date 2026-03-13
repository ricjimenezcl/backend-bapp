-- ============================================================
-- Migración 004 — Correcciones de Schema (Seguridad + Calidad)
-- Autor: Phase 4 Security Hardening
-- Prerequisitos: 001_initial, 002, 003 ejecutadas
-- Idempotente: Sí — seguro para re-ejecutar
-- ============================================================

BEGIN;

-- ────────────────────────────────────────────────────────────
-- 1. user_profiles.rating_avg: int4 → numeric(3,2)
--    Ratings como 4.5 se truncaban a 4
-- ────────────────────────────────────────────────────────────
ALTER TABLE user_profiles
  ALTER COLUMN rating_avg TYPE numeric(3,2)
  USING rating_avg::numeric(3,2);

COMMENT ON COLUMN user_profiles.rating_avg IS
  'Rating promedio del cliente (0.00–5.00). Corrección: era int4, perdía decimales.';


-- ────────────────────────────────────────────────────────────
-- 2. notifications.is_read: NULL → NOT NULL DEFAULT false
--    Simplifica queries: WHERE is_read = false sin IS FALSE
-- ────────────────────────────────────────────────────────────
UPDATE notifications
  SET is_read = false
  WHERE is_read IS NULL;

ALTER TABLE notifications
  ALTER COLUMN is_read SET NOT NULL,
  ALTER COLUMN is_read SET DEFAULT false;


-- ────────────────────────────────────────────────────────────
-- 3. Eliminar triggers duplicados en bookings
--    Síntoma: 2 triggers ejecutaban update_updated_at_column()
--    en la misma tabla ante cada cambio.
--    Mantenemos el trigger con nombre estándar (update_*).
-- ────────────────────────────────────────────────────────────
DROP TRIGGER IF EXISTS trigger_update_bookings_updated_at ON bookings;
-- El trigger correcto que permanece:
-- update_bookings_updated_at → llama update_updated_at_column()


-- ────────────────────────────────────────────────────────────
-- 4. Eliminar triggers duplicados en payments
-- ────────────────────────────────────────────────────────────
DROP TRIGGER IF EXISTS trigger_update_payments_updated_at ON payments;
-- El trigger correcto que permanece:
-- update_payments_updated_at → llama update_updated_at_column()


-- ────────────────────────────────────────────────────────────
-- 5. Reparar FK bookings.provider_id
--    La constraint estaba declarada NULL (sin efecto real).
--    Ahora apunta correctamente a providers.id.
-- ────────────────────────────────────────────────────────────
ALTER TABLE bookings
  DROP CONSTRAINT IF EXISTS bookings_provider_id_fkey;

-- Solo agregar si la columna provider_id existe y providers.id existe
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'bookings' AND column_name = 'provider_id'
  ) THEN
    ALTER TABLE bookings
      ADD CONSTRAINT bookings_provider_id_fkey
      FOREIGN KEY (provider_id)
      REFERENCES providers(id)
      ON DELETE SET NULL;
  END IF;
END $$;


-- ────────────────────────────────────────────────────────────
-- Validación
-- ────────────────────────────────────────────────────────────
DO $$
DECLARE
  v_type text;
  v_not_null boolean;
BEGIN
  -- Verificar tipo de rating_avg
  SELECT data_type INTO v_type
    FROM information_schema.columns
    WHERE table_name = 'user_profiles' AND column_name = 'rating_avg';
  IF v_type NOT IN ('numeric', 'double precision') THEN
    RAISE WARNING 'user_profiles.rating_avg tipo inesperado: %', v_type;
  END IF;

  -- Verificar NOT NULL en notifications.is_read
  SELECT is_nullable = 'NO' INTO v_not_null
    FROM information_schema.columns
    WHERE table_name = 'notifications' AND column_name = 'is_read';
  IF NOT v_not_null THEN
    RAISE WARNING 'notifications.is_read sigue siendo nullable';
  END IF;

  RAISE NOTICE 'Migración 004 completada correctamente';
END $$;

COMMIT;


-- ────────────────────────────────────────────────────────────
-- 6. Índices compuestos en tablas de chat
--    Fuera del bloque BEGIN/COMMIT: CREATE INDEX no puede
--    usar CONCURRENTLY dentro de una transacción explícita.
-- ────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_chat_conv_client_provider
  ON chat_conversations (client_id, provider_id);

CREATE INDEX IF NOT EXISTS idx_chat_msg_conv_created
  ON chat_messages (conversation_id, created_at DESC);


-- ────────────────────────────────────────────────────────────
-- ROLLBACK (ejecutar manualmente si se necesita revertir)
-- ────────────────────────────────────────────────────────────
-- ALTER TABLE user_profiles ALTER COLUMN rating_avg TYPE integer USING rating_avg::integer;
-- ALTER TABLE notifications ALTER COLUMN is_read DROP NOT NULL;
-- ALTER TABLE notifications ALTER COLUMN is_read DROP DEFAULT;
-- DROP INDEX IF EXISTS idx_chat_conv_client_provider;
-- DROP INDEX IF EXISTS idx_chat_msg_conv_created;

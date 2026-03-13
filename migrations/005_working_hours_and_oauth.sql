-- ============================================================
-- Migración 005 — Horarios de Proveedor + OAuth Social Login
-- BAPP Search
--
-- Prerequisitos: 001, 002, 003, 004 ejecutadas
--
-- Ejecución:
--   psql $DATABASE_URL -f migrations/005_working_hours_and_oauth.sql
--
-- Estrategia: ADDITIVE + idempotente (IF NOT EXISTS / IF NOT EXISTS)
-- ============================================================

BEGIN;

-- ============================================================
-- BLOQUE 1 — Tabla de horarios de trabajo del proveedor
-- ============================================================

CREATE TABLE IF NOT EXISTS provider_working_hours (
    id          SERIAL PRIMARY KEY,
    provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
    day_of_week SMALLINT NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
        -- 0=Lunes, 1=Martes, ..., 5=Sábado, 6=Domingo
        -- Coincide con Python datetime.weekday() (0=Monday)
    start_time  TIME NOT NULL,
    end_time    TIME NOT NULL,
    is_active   BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_working_hours_end_after_start CHECK (end_time > start_time),
    UNIQUE (provider_id, day_of_week)
);

CREATE INDEX IF NOT EXISTS idx_working_hours_provider
    ON provider_working_hours(provider_id);

CREATE INDEX IF NOT EXISTS idx_working_hours_active
    ON provider_working_hours(provider_id, day_of_week)
    WHERE is_active = true;

-- Trigger updated_at automático
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_working_hours_updated_at ON provider_working_hours;
CREATE TRIGGER update_working_hours_updated_at
    BEFORE UPDATE ON provider_working_hours
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'provider_working_hours') THEN
        RAISE NOTICE '✅ Tabla provider_working_hours creada/verificada';
    ELSE
        RAISE EXCEPTION '❌ Error creando tabla provider_working_hours';
    END IF;
END $$;


-- ============================================================
-- BLOQUE 2 — Campos OAuth en tabla users
-- ============================================================

ALTER TABLE users ADD COLUMN IF NOT EXISTS oauth_provider    VARCHAR(20);
ALTER TABLE users ADD COLUMN IF NOT EXISTS oauth_id          VARCHAR(255);
ALTER TABLE users ADD COLUMN IF NOT EXISTS oauth_avatar_url  VARCHAR(500);

-- Índice único para buscar por proveedor OAuth + id externo
-- Parcial: solo cuando oauth_provider IS NOT NULL (evita conflictos en usuarios normales)
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_oauth_provider_id
    ON users(oauth_provider, oauth_id)
    WHERE oauth_provider IS NOT NULL;

-- Comentarios descriptivos
COMMENT ON COLUMN users.oauth_provider IS
    'Proveedor OAuth social: google | facebook | NULL para usuarios con password';
COMMENT ON COLUMN users.oauth_id IS
    'ID único del usuario en el proveedor OAuth externo (sub de Google, id de Facebook)';
COMMENT ON COLUMN users.oauth_avatar_url IS
    'URL de foto de perfil proporcionada por el proveedor OAuth';

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'oauth_provider'
    ) THEN
        RAISE NOTICE '✅ Campos OAuth agregados a tabla users';
    ELSE
        RAISE EXCEPTION '❌ Error agregando campos OAuth a users';
    END IF;
END $$;


-- ============================================================
-- BLOQUE 3 — Corregir user_profiles.rating_avg (int4 → numeric)
-- Idempotente: ya ejecutada en 004, pero si 004 no se aplicó,
-- este bloque la cubre aquí también.
-- ============================================================

DO $$
DECLARE
    v_type text;
BEGIN
    SELECT data_type INTO v_type
    FROM information_schema.columns
    WHERE table_name = 'user_profiles' AND column_name = 'rating_avg';

    IF v_type IN ('integer', 'int4', 'smallint') THEN
        ALTER TABLE user_profiles
            ALTER COLUMN rating_avg TYPE NUMERIC(3,2)
            USING COALESCE(rating_avg, 0)::NUMERIC(3,2);
        RAISE NOTICE '✅ user_profiles.rating_avg corregido a numeric(3,2)';
    ELSE
        RAISE NOTICE 'ℹ️  user_profiles.rating_avg ya es %: no requiere corrección', v_type;
    END IF;
END $$;


-- ============================================================
-- BLOQUE 4 — Índices trigram para búsqueda de texto (Obj 7)
-- Requiere extensión pg_trgm (disponible en Render/Supabase/Neon)
-- ============================================================

DO $$
BEGIN
    -- Activar extensión pg_trgm si existe
    IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'pg_trgm') THEN
        CREATE EXTENSION IF NOT EXISTS pg_trgm;

        -- Índice GIN trigram para búsqueda ILIKE eficiente en business_name
        EXECUTE 'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sp_business_name_trgm
            ON service_providers USING gin(business_name gin_trgm_ops)';

        -- Índice GIN trigram para búsqueda en description
        EXECUTE 'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sp_description_trgm
            ON service_providers USING gin(description gin_trgm_ops)';

        RAISE NOTICE '✅ Índices trigram creados (búsqueda text-search acelerada)';
    ELSE
        RAISE WARNING '⚠️  pg_trgm no disponible — búsqueda text-search usará ILIKE sin índice (funcional, más lento)';
    END IF;
EXCEPTION
    WHEN OTHERS THEN
        RAISE WARNING '⚠️  Error creando índices trigram (no crítico): %', SQLERRM;
END $$;


-- ============================================================
-- Validación final
-- ============================================================

DO $$
DECLARE
    v_tables_ok boolean;
    v_oauth_ok  boolean;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM information_schema.tables WHERE table_name = 'provider_working_hours'
    ) INTO v_tables_ok;

    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'oauth_provider'
    ) INTO v_oauth_ok;

    IF v_tables_ok AND v_oauth_ok THEN
        RAISE NOTICE '🎉 Migración 005 completada exitosamente';
    ELSE
        RAISE EXCEPTION '❌ Migración 005 incompleta: tabla_ok=%, oauth_ok=%', v_tables_ok, v_oauth_ok;
    END IF;
END $$;


COMMIT;


-- ============================================================
-- ROLLBACK (ejecutar manualmente si se necesita revertir)
-- ============================================================
-- DROP TABLE IF EXISTS provider_working_hours;
-- ALTER TABLE users DROP COLUMN IF EXISTS oauth_provider;
-- ALTER TABLE users DROP COLUMN IF EXISTS oauth_id;
-- ALTER TABLE users DROP COLUMN IF EXISTS oauth_avatar_url;
-- DROP INDEX CONCURRENTLY IF EXISTS idx_users_oauth_provider_id;
-- DROP INDEX CONCURRENTLY IF EXISTS idx_sp_business_name_trgm;
-- DROP INDEX CONCURRENTLY IF EXISTS idx_sp_description_trgm;

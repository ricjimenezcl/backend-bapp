-- ============================================================
-- Migración 003 — PostGIS Geoespacial
-- BAPP Search — Fase 3
--
-- Requisitos:
--   - PostgreSQL 12+ con extensión PostGIS disponible
--   - En Render/Supabase/Neon: habilitada por defecto
--   - En Postgres.app o Docker: puede requerir superuser
--
-- Ejecución:
--   psql $DATABASE_URL -f migrations/003_postgis_geolocation.sql
--
-- Estrategia: ADDITIVE — no elimina nada, solo agrega.
--   Las columnas latitude/longitude permanecen intactas.
--   La columna location es nullable durante la transición.
--   El trigger sync mantiene los tres en sincronía.
-- ============================================================


-- ============================================================
-- PASO 1 — Instalar extensión PostGIS (idempotente)
-- ============================================================
CREATE EXTENSION IF NOT EXISTS postgis;

-- Verificar instalación (informativo)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'postgis') THEN
        RAISE NOTICE 'PostGIS version: %', PostGIS_Version();
    ELSE
        RAISE EXCEPTION 'PostGIS installation failed';
    END IF;
END $$;


-- ============================================================
-- PASO 2 — Agregar columna geometry a service_providers
-- nullable=true para compatibilidad durante migración
-- ============================================================
ALTER TABLE service_providers
    ADD COLUMN IF NOT EXISTS location geometry(Point, 4326);

-- Verificar columna
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'service_providers' AND column_name = 'location'
    ) THEN
        RAISE NOTICE '✅ Columna location agregada a service_providers';
    ELSE
        RAISE EXCEPTION '❌ Error agregando columna location';
    END IF;
END $$;


-- ============================================================
-- PASO 3 — Backfill desde lat/lng existentes
-- ST_MakePoint(X=longitude, Y=latitude) — orden correcto WGS84
-- ============================================================
UPDATE service_providers
SET location = ST_SetSRID(
    ST_MakePoint(longitude::float, latitude::float),
    4326
)
WHERE latitude IS NOT NULL
  AND longitude IS NOT NULL
  AND location IS NULL;

-- Diagnóstico del backfill
DO $$
DECLARE
    v_total   int;
    v_with_geo int;
    v_missing  int;
BEGIN
    SELECT
        COUNT(*),
        COUNT(location),
        COUNT(*) - COUNT(location)
    INTO v_total, v_with_geo, v_missing
    FROM service_providers;

    RAISE NOTICE 'Backfill: total=% with_geometry=% missing=%',
        v_total, v_with_geo, v_missing;

    IF v_missing > 0 THEN
        RAISE WARNING '⚠️ % filas sin geometría (lat/lng nulos)', v_missing;
    ELSE
        RAISE NOTICE '✅ Backfill completo — todas las filas tienen geometría';
    END IF;
END $$;


-- ============================================================
-- PASO 4 — Índice GiST principal
-- Nota: sin CONCURRENTLY para compatibilidad con scripts de migración.
-- En producción con carga activa, ejecuta manualmente con CONCURRENTLY vía psql.
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_service_providers_geo
    ON service_providers USING GIST(location);

-- Índice parcial — solo proveedores aprobados y disponibles
-- Este es el índice activo en el 99% de las búsquedas de usuarios
CREATE INDEX IF NOT EXISTS idx_service_providers_geo_active
    ON service_providers USING GIST(location)
    WHERE validation_status = 'approved' AND is_available = true;

-- Verificar índices
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE tablename = 'service_providers'
        AND indexname = 'idx_service_providers_geo_active'
    ) THEN
        RAISE NOTICE '✅ Índice GiST creado: idx_service_providers_geo_active';
    ELSE
        RAISE EXCEPTION '❌ Error creando índice GiST';
    END IF;
END $$;


-- ============================================================
-- PASO 5 — Trigger de sincronía lat/lng ↔ location
-- Garantiza que al actualizar lat o lng, location se regenera
-- ============================================================
CREATE OR REPLACE FUNCTION sync_provider_location()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.latitude IS NOT NULL AND NEW.longitude IS NOT NULL THEN
        NEW.location = ST_SetSRID(
            ST_MakePoint(NEW.longitude::float, NEW.latitude::float),
            4326
        );
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Crear trigger (DROP primero para idempotencia)
DROP TRIGGER IF EXISTS trg_sync_provider_location ON service_providers;

CREATE TRIGGER trg_sync_provider_location
    BEFORE INSERT OR UPDATE OF latitude, longitude
    ON service_providers
    FOR EACH ROW
    EXECUTE FUNCTION sync_provider_location();

DO $$ BEGIN RAISE NOTICE '✅ Trigger trg_sync_provider_location creado'; END $$;


-- ============================================================
-- PASO 6 — Test de validación final
-- ============================================================

-- Test 1: ST_DWithin query (simula la query de producción)
DO $$
DECLARE
    v_count int;
BEGIN
    -- Santiago centro (lat=-33.45, lng=-70.67) radio 50km
    SELECT COUNT(*) INTO v_count
    FROM service_providers
    WHERE location IS NOT NULL
      AND ST_DWithin(
          location::geography,
          ST_SetSRID(ST_MakePoint(-70.6693, -33.4489), 4326)::geography,
          50000  -- 50km en metros
      );
    RAISE NOTICE '✅ Test ST_DWithin: % proveedores en 50km de Santiago', v_count;
END $$;

-- Test 2: ST_Distance (simula cálculo de distancia exacta)
DO $$
DECLARE
    v_sample record;
BEGIN
    SELECT
        business_name,
        ROUND((ST_Distance(
            location::geography,
            ST_SetSRID(ST_MakePoint(-70.6693, -33.4489), 4326)::geography
        ) / 1000.0)::numeric, 2) AS distance_km
    INTO v_sample
    FROM service_providers
    WHERE location IS NOT NULL
    LIMIT 1;

    IF v_sample IS NOT NULL THEN
        RAISE NOTICE '✅ Test ST_Distance: "%" está a % km de Santiago',
            v_sample.business_name, v_sample.distance_km;
    ELSE
        RAISE NOTICE '⚠️ Sin proveedores para test ST_Distance (tabla vacía)';
    END IF;
END $$;


-- ============================================================
-- ROLLBACK — Ejecutar SOLO en caso de revert
-- (NO ejecutar en la migración normal)
-- ============================================================
-- DROP TRIGGER IF EXISTS trg_sync_provider_location ON service_providers;
-- DROP FUNCTION IF EXISTS sync_provider_location();
-- DROP INDEX CONCURRENTLY IF EXISTS idx_service_providers_geo_active;
-- DROP INDEX CONCURRENTLY IF EXISTS idx_service_providers_geo;
-- ALTER TABLE service_providers DROP COLUMN IF EXISTS location;
-- DROP EXTENSION IF EXISTS postgis CASCADE;  -- ⚠️ solo si no hay otras tablas con geometry


-- ============================================================
-- CLEANUP — Ejecutar SOLO después de 2 semanas estable con USE_POSTGIS=True
-- ============================================================
-- DROP INDEX CONCURRENTLY IF EXISTS idx_service_providers_location;
-- (Elimina el índice B-tree viejo de lat/lng — el GiST lo reemplaza)


DO $$ BEGIN RAISE NOTICE '🎉 Migración 003_postgis_geolocation completada exitosamente'; END $$;

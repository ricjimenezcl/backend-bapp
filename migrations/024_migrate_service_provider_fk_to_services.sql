-- Migración 024: Mueve service_providers.service_id FK
-- de service_categories(id) → services(id)
--
-- Pasos:
-- 1. Agrega columna temporal new_service_id → services(id)
-- 2. Rellena new_service_id haciendo JOIN por nombre con la tabla services
-- 3. Para filas que no matchean (servicio no está en nuevo catálogo),
--    inserta el nombre viejo en services bajo la subcategoría general
-- 4. Elimina FK y columna service_id vieja
-- 5. Renombra new_service_id a service_id y agrega nueva FK

-- ------------------------------------------------------------
-- PASO 1: columna temporal
-- ------------------------------------------------------------
ALTER TABLE service_providers
    ADD COLUMN IF NOT EXISTS new_service_id INTEGER;

-- ------------------------------------------------------------
-- PASO 2: match por nombre (JOIN service_categories → services)
-- ------------------------------------------------------------
UPDATE service_providers sp
SET new_service_id = s.id
FROM service_categories sc
JOIN services s
  ON LOWER(TRIM(s.name)) = LOWER(TRIM(sc.name))
WHERE sc.id = sp.service_id
  AND sp.new_service_id IS NULL;

-- ------------------------------------------------------------
-- PASO 3: filas sin match → crear entrada en services
-- (se insertan bajo subcategory_id = 1 como fallback, id no conocida)
-- ------------------------------------------------------------
WITH unmatched AS (
    SELECT DISTINCT sp.service_id, sc.name
    FROM service_providers sp
    JOIN service_categories sc ON sc.id = sp.service_id
    WHERE sp.new_service_id IS NULL
      AND sc.name IS NOT NULL
),
inserted AS (
    INSERT INTO services (name, subcategory_id, created_at, updated_at)
    SELECT name, 1, NOW(), NOW()
    FROM unmatched
    ON CONFLICT DO NOTHING
    RETURNING id, name
)
UPDATE service_providers sp
SET new_service_id = ins.id
FROM inserted ins
JOIN service_categories sc ON LOWER(TRIM(sc.name)) = LOWER(TRIM(ins.name))
WHERE sc.id = sp.service_id
  AND sp.new_service_id IS NULL;

-- ------------------------------------------------------------
-- PASO 4: eliminar FK vieja y columna service_id
-- (solo si todas las filas tienen new_service_id relleno)
-- ------------------------------------------------------------
DO $$
DECLARE
    orphan_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO orphan_count
    FROM service_providers
    WHERE new_service_id IS NULL;

    IF orphan_count > 0 THEN
        RAISE EXCEPTION 'Migración 024 abortada: % filas de service_providers sin new_service_id. Revisar datos.', orphan_count;
    END IF;

    -- Eliminar FK vieja
    ALTER TABLE service_providers
        DROP CONSTRAINT IF EXISTS service_providers_service_id_fkey;

    -- Eliminar columna vieja
    ALTER TABLE service_providers DROP COLUMN service_id;

    -- Renombrar columna nueva
    ALTER TABLE service_providers RENAME COLUMN new_service_id TO service_id;

    -- Agregar nueva FK → services(id)
    ALTER TABLE service_providers
        ADD CONSTRAINT service_providers_service_id_fkey
        FOREIGN KEY (service_id) REFERENCES services(id) ON DELETE RESTRICT;

    RAISE NOTICE 'Migración 024 completada: FK service_providers.service_id ahora apunta a services(id)';
END;
$$;

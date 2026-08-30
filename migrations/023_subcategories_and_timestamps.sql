-- ============================================================================
-- 023: Crear tabla subcategories + corregir DEFAULT de created_at
-- ============================================================================

-- 1. Corregir created_at sin DEFAULT en tablas principales
--    (evita NULL que rompe la serialización Pydantic)
ALTER TABLE main_categories
    ALTER COLUMN created_at SET DEFAULT NOW();

UPDATE main_categories
    SET created_at = NOW()
    WHERE created_at IS NULL;

ALTER TABLE service_categories
    ALTER COLUMN created_at SET DEFAULT NOW();

UPDATE service_categories
    SET created_at = NOW()
    WHERE created_at IS NULL;

-- 2. Crear tabla subcategories (si no existe)
CREATE TABLE IF NOT EXISTS subcategories (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(150) NOT NULL,
    description TEXT,
    icon        VARCHAR(255),
    main_category_id INTEGER NOT NULL
        REFERENCES main_categories(id) ON DELETE CASCADE,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_subcategories_main_category_id
    ON subcategories(main_category_id);

-- 3. Agregar columnas faltantes a services (si la tabla ya existe con schema viejo)
ALTER TABLE services
    ADD COLUMN IF NOT EXISTS icon VARCHAR(255);

ALTER TABLE services
    ADD COLUMN IF NOT EXISTS subcategory_id INTEGER
        REFERENCES subcategories(id) ON DELETE SET NULL;

ALTER TABLE services
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();

-- 4. Corregir created_at de services
ALTER TABLE services
    ALTER COLUMN created_at SET DEFAULT NOW();

UPDATE services
    SET created_at = NOW()
    WHERE created_at IS NULL;

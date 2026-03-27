-- Migration 015: Geocode cache table
-- Prevents re-geocoding the same address twice (saves cost + latency).
-- One row per normalized address per country.

CREATE TABLE IF NOT EXISTS geocode_cache (
    id              SERIAL PRIMARY KEY,
    country_code    CHAR(2)          NOT NULL DEFAULT 'CL',
    address_normalized TEXT          NOT NULL,
    lat             DOUBLE PRECISION NOT NULL,
    lng             DOUBLE PRECISION NOT NULL,
    raw_response    JSONB,
    hit_count       INTEGER          NOT NULL DEFAULT 1,
    created_at      TIMESTAMP        NOT NULL DEFAULT NOW(),
    last_used_at    TIMESTAMP        NOT NULL DEFAULT NOW(),
    UNIQUE (country_code, address_normalized)
);

CREATE INDEX IF NOT EXISTS ix_geocode_cache_country_address
    ON geocode_cache (country_code, address_normalized);

CREATE INDEX IF NOT EXISTS ix_geocode_cache_last_used
    ON geocode_cache (last_used_at);

-- Address search index table (for autocomplete without external API)
-- Populated lazily as users geocode addresses.
CREATE TABLE IF NOT EXISTS address_index (
    id              SERIAL PRIMARY KEY,
    country_code    CHAR(2)          NOT NULL DEFAULT 'CL',
    display_text    TEXT             NOT NULL,
    lat             DOUBLE PRECISION NOT NULL,
    lng             DOUBLE PRECISION NOT NULL,
    popularity      INTEGER          NOT NULL DEFAULT 0,
    search_vector   tsvector,
    created_at      TIMESTAMP        NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_address_index_search
    ON address_index USING GIN(search_vector);

CREATE INDEX IF NOT EXISTS ix_address_index_country_pop
    ON address_index (country_code, popularity DESC);

DO $$ BEGIN
    RAISE NOTICE 'Migration 015: geocode_cache and address_index tables created.';
END $$;

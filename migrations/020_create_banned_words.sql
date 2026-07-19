-- ============================================
-- MIGRACION 020: Tabla banned_words para filtro de contenido
-- Fecha: 2026-07-18
-- ============================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'banned_word_severity') THEN
        CREATE TYPE banned_word_severity AS ENUM ('block', 'flag');
    END IF;
END$$;

CREATE TABLE IF NOT EXISTS banned_words (
    id SERIAL PRIMARY KEY,
    word VARCHAR(120) NOT NULL UNIQUE,
    severity banned_word_severity NOT NULL DEFAULT 'block',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_banned_words_severity ON banned_words (severity);
CREATE INDEX IF NOT EXISTS idx_banned_words_created_at ON banned_words (created_at DESC);

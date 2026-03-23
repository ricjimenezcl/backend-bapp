-- ============================================================
-- Migración 012 — Aceptación de Términos y Consentimiento Email
-- Propósito: registrar si el usuario aceptó los T&C y si
--            consintió recibir emails de marketing.
--
-- Columnas:
--   terms_accepted     → TRUE cuando el usuario aceptó los T&C
--   terms_accepted_at  → timestamp exacto de aceptación
--   email_opt_in       → TRUE si el usuario consintió emails
-- ============================================================

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS terms_accepted    BOOLEAN     NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS terms_accepted_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS email_opt_in      BOOLEAN     NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN users.terms_accepted IS
    'Indica si el usuario aceptó los Términos y Condiciones de uso.';

COMMENT ON COLUMN users.terms_accepted_at IS
    'Momento exacto en que el usuario aceptó los T&C (NULL si aún no los aceptó).';

COMMENT ON COLUMN users.email_opt_in IS
    'Consentimiento explícito para recibir comunicaciones de marketing por email.';

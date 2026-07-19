-- Permite el mismo email para distintos roles (CLIENT / PROVIDER)
-- Mantiene unicidad por combinación email(normalizado)+rol.

DO $$
DECLARE
    c_name text;
BEGIN
    -- Eliminar constraint UNIQUE antigua sobre users.email (si existe)
    SELECT conname
      INTO c_name
      FROM pg_constraint
     WHERE conrelid = 'users'::regclass
       AND contype = 'u'
       AND conname = 'users_email_key';

    IF c_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE users DROP CONSTRAINT %I', c_name);
    END IF;
END $$;

-- Eliminar índice único directo sobre users.email (si existe con nombre clásico)
DROP INDEX IF EXISTS ix_users_email;

-- Crear unicidad por email normalizado + rol
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email_role
ON users ((lower(btrim(email))), role);

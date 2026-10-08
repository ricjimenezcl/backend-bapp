-- Migración 032: Corrige FK service_providers.provider_id
-- de users(id) (legacy) → providers(id) (correcto)
--
-- Hallazgo (error reportado en producción al crear un servicio):
--   Error creating service: IntegrityError: insert or update on table
--   "service_providers" violates foreign key constraint
--   "service_providers_provider_id_fkey"
--   Key (provider_id)=(76) is not present in table "users".
--
-- El modelo SQLAlchemy (app/models/provider.py::ServiceProvider.provider_id)
-- y todo el código de aplicación (app/services/provider_service.py::
-- create_service_provider) asumen y validan correctamente que
-- service_providers.provider_id referencia a providers(id) — de hecho el
-- endpoint hace `select(Provider).where(Provider.id == service_data.provider_id)`
-- y encuentra el proveedor sin problema (no es un 404).
--
-- Pero la constraint REAL que existe en la base de datos de producción
-- (heredada de una versión muy antigua del esquema, antes de que "providers"
-- existiera como tabla separada de "users") seguía apuntando a users(id).
-- Como providers.id y users.id son secuencias independientes, un provider
-- cuyo providers.id (ej. 76) no coincide con ningún users.id existente hace
-- que el INSERT falle en la base de datos aunque la validación de la app
-- haya sido correcta.
--
-- Mismo tipo de problema (constraint legacy desalineada tras separar tablas)
-- que ya se corrigió para service_providers.service_id en la migración 024.
--
-- Esta migración:
-- 1) Verifica que no existan filas huérfanas (provider_id que no exista en
--    providers(id)) antes de tocar la constraint — si las hay, aborta para
--    revisar los datos manualmente.
-- 2) Elimina la FK legacy (apunta a users(id)).
-- 3) Agrega la FK correcta → providers(id) ON DELETE CASCADE, consistente
--    con el resto de las FKs de este monorepo hacia providers(id)
--    (ver 005_working_hours_and_oauth.sql, 009_monetization_system.sql).

DO $$
DECLARE
    orphan_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO orphan_count
    FROM service_providers sp
    LEFT JOIN providers p ON p.id = sp.provider_id
    WHERE p.id IS NULL;

    IF orphan_count > 0 THEN
        RAISE EXCEPTION 'Migración 032 abortada: % filas de service_providers con provider_id que no existe en providers(id). Revisar datos antes de continuar.', orphan_count;
    END IF;

    -- Eliminar la FK legacy (actualmente apunta a users(id))
    ALTER TABLE service_providers
        DROP CONSTRAINT IF EXISTS service_providers_provider_id_fkey;

    -- Agregar la FK correcta → providers(id)
    ALTER TABLE service_providers
        ADD CONSTRAINT service_providers_provider_id_fkey
        FOREIGN KEY (provider_id) REFERENCES providers(id) ON DELETE CASCADE;

    RAISE NOTICE 'Migración 032 completada: FK service_providers.provider_id ahora apunta a providers(id)';
END;
$$;

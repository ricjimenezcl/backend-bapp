-- Migración 025: contador persistente del cupo gratuito de servicios
--
-- Problema: el endpoint POST /providers/services decidía si un servicio nuevo
-- era gratuito contando filas actuales en service_providers
-- (SELECT COUNT(*) FROM service_providers WHERE provider_id = :pid).
-- Como DELETE /providers/{id}/services/{id} borra la fila físicamente, un
-- proveedor podía crear 2 servicios gratis, eliminar uno, y crear otro gratis
-- de nuevo indefinidamente (el conteo bajaba junto con la fila eliminada).
--
-- Fix: se agrega providers.free_services_used, un contador que SOLO SUBE.
-- El backend ahora valida y decrementa el cupo gratuito contra esta columna
-- en vez de contar filas vivas en service_providers.

ALTER TABLE providers
    ADD COLUMN IF NOT EXISTS free_services_used SMALLINT NOT NULL DEFAULT 0;

ALTER TABLE providers
    DROP CONSTRAINT IF EXISTS chk_providers_free_services_used;

ALTER TABLE providers
    ADD CONSTRAINT chk_providers_free_services_used CHECK (free_services_used >= 0);

-- Backfill best-effort para proveedores existentes: usan como mínimo la
-- cantidad de servicios que tienen HOY (tope 2, que es el cupo gratuito).
-- No es posible reconstruir servicios ya eliminados antes de esta migración,
-- por lo que un proveedor que ya evadió el límite en el pasado no queda
-- automáticamente marcado como "cupo agotado" — pero desde este punto en
-- adelante el contador ya no podrá volver a bajar.
UPDATE providers p
SET free_services_used = LEAST(sub.cnt, 2)
FROM (
    SELECT provider_id, COUNT(*) AS cnt
    FROM service_providers
    GROUP BY provider_id
) sub
WHERE sub.provider_id = p.id
  AND p.free_services_used < LEAST(sub.cnt, 2);

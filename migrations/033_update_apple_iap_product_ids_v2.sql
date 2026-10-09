-- Migración 033: Actualizar platform_product_id de apple_iap al sufijo "_v2"
--
-- Los 5 Product IDs de App Store Connect para iOS (bapp_client_unlock_7,
-- bapp_client_unlock_30, bapp_provider_plan_7d, bapp_provider_plan_monthly,
-- bapp_provider_plan_annual) se habían creado originalmente como tipo
-- "No consumible". Ese tipo es incorrecto para planes de acceso temporal
-- que el usuario debe poder volver a comprar tras vencer (con "No
-- consumible", Apple solo permite comprarlo UNA vez por Apple ID para
-- siempre, y "Restaurar compras" lo devolvería gratis indefinidamente).
--
-- Apple no permite cambiar el tipo de un producto ya creado, así que esos
-- borradores se eliminaron y se recrearon con tipo "Consumible" (único tipo
-- disponible en esta cuenta que permite recompra tras expirar el período).
-- Pero Apple reserva PERMANENTEMENTE cualquier Product ID usado alguna vez,
-- incluso si se elimina en estado borrador, por lo que los nuevos productos
-- usan el sufijo "_v2" para evitar el conflicto de ID duplicado.
--
-- Ver también: frontend-bapp/src/app/services/apple-iap.service.ts
-- (IOS_PRODUCT_ID_MAP ya actualizado con el sufijo _v2) y el dashboard de
-- RevenueCat (Product catalog), que también debe actualizarse para apuntar
-- a los nuevos IDs _v2.
--
-- Solo afecta platform='apple_iap'; los mapeos de 'google_play' y 'web'
-- no cambian (Android no tuvo este problema de reutilización de ID).

UPDATE platform_products
SET platform_product_id = platform_product_id || '_v2'
WHERE platform = 'apple_iap'
  AND platform_product_id IN (
    'bapp_client_unlock_7',
    'bapp_client_unlock_30',
    'bapp_provider_plan_7d',
    'bapp_provider_plan_monthly',
    'bapp_provider_plan_annual'
  );

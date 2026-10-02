-- Migración 030: Mapeo RevenueCat (apple_iap/google_play) para planes bundle
--
-- Completa el catálogo multiplataforma de los 3 planes bundle de proveedor
-- (migración 029) agregando sus IDs de producto para iOS (App Store vía
-- RevenueCat) y Android (Play Store vía RevenueCat), necesarios para que
-- el nuevo webhook `/api/v1/payments/revenuecat/webhook` pueda resolver
-- `product_id` del evento -> Product interno.
--
-- IMPORTANTE (acción manual pendiente, fuera del alcance de esta migración):
--   1. Crear estos 3 productos en RevenueCat (Product catalog > Products)
--      con EXACTAMENTE estos platform_product_id, para ambas apps
--      (App Store y Play Store).
--   2. Crear los In-App Purchases correspondientes en App Store Connect
--      (tipo: Non-Consumable o Non-Renewing Subscription, NO auto-renovable
--      — son compras únicas, confirmado con el negocio) y en Play Console
--      (producto "one-time" / in-app product, no suscripción).
--   3. Desactivar/archivar en RevenueCat los 2 productos viejos de
--      proveedor que ya no aplican al nuevo modelo de 3 planes:
--      bapp_provider_service_30 y bapp_provider_leads_7 (los de cliente,
--      bapp_client_unlock_7/30, NO cambian).
--   4. Configurar en RevenueCat (Project settings > Integrations > Webhooks)
--      la URL del webhook + el valor de "Authorization header", y setear
--      ese mismo valor en la env var REVENUECAT_WEBHOOK_AUTH_HEADER del backend.
--
-- Los platform_product_id usan el mismo string para iOS y Android por
-- simplicidad (RevenueCat permite IDs distintos por tienda si se prefiere).

INSERT INTO platform_products (product_id, platform, platform_product_id, platform_price, is_active)
SELECT id, 'apple_iap',
    CASE sku
        WHEN 'provider_plan_7days' THEN 'bapp_provider_plan_7d'
        WHEN 'provider_plan_monthly' THEN 'bapp_provider_plan_monthly'
        WHEN 'provider_plan_annual' THEN 'bapp_provider_plan_annual'
    END,
    price_clp::text,
    true
FROM products
WHERE sku IN ('provider_plan_7days', 'provider_plan_monthly', 'provider_plan_annual')
ON CONFLICT (product_id, platform) DO NOTHING;

INSERT INTO platform_products (product_id, platform, platform_product_id, platform_price, is_active)
SELECT id, 'google_play',
    CASE sku
        WHEN 'provider_plan_7days' THEN 'bapp_provider_plan_7d'
        WHEN 'provider_plan_monthly' THEN 'bapp_provider_plan_monthly'
        WHEN 'provider_plan_annual' THEN 'bapp_provider_plan_annual'
    END,
    price_clp::text,
    true
FROM products
WHERE sku IN ('provider_plan_7days', 'provider_plan_monthly', 'provider_plan_annual')
ON CONFLICT (product_id, platform) DO NOTHING;

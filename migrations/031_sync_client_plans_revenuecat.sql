-- Migración 031: Sincronizar catálogo de planes CLIENTE con RevenueCat/App Store
--
-- Hallazgo: los 2 planes de cliente (7 días / 30 días) ya existían como
-- Product + estaban expuestos en la UI (web-bapp PaymentComponent y
-- frontend-bapp main-categories/client-profile/service-search/provider-info/
-- provider-action-sheet vía PaymentRedirectService.openClientUnlock/
-- openClientUnlock30), y ya funcionaban vía Transbank y Mercado Pago.
--
-- Pero el mapeo `platform_products` para apple_iap (RevenueCat/iOS) estaba
-- roto:
--   - CLIENT_UNLOCK_7 (sku premium_access_7days): la fila apple_iap existente
--     (migración 009) usaba platform_product_id='premium_access_7days', que
--     NO coincide con el producto real configurado en App Store Connect/
--     RevenueCat ('bapp_client_unlock_7', ver IOS_PRODUCT_ID_MAP en
--     frontend-bapp/apple-iap.service.ts y el dashboard de RevenueCat).
--     Esto hacía que el webhook de RevenueCat (migración 030) nunca pudiera
--     resolver este producto -> el beneficio jamás se habría activado para
--     una compra real de este plan en iOS.
--   - CLIENT_UNLOCK_30 (sku client_unlock_30days): no tenía NINGUNA fila
--     apple_iap (solo 'web', migración 026) -> mismo problema, pero total.
--
-- Esta migración corrige ambos para que los 2 planes de cliente queden
-- igual de sincronizados que los 3 planes de proveedor (migración 030).

-- 1) Corregir el ID de Apple IAP para CLIENT_UNLOCK_7 (premium_access_7days)
UPDATE platform_products
SET platform_product_id = 'bapp_client_unlock_7'
WHERE platform = 'apple_iap'
  AND product_id = (SELECT id FROM products WHERE sku = 'premium_access_7days')
  AND platform_product_id <> 'bapp_client_unlock_7';

-- 2) Agregar el mapeo Apple IAP faltante para CLIENT_UNLOCK_30
INSERT INTO platform_products (product_id, platform, platform_product_id, platform_price, is_active)
SELECT id, 'apple_iap', 'bapp_client_unlock_30', price_clp::text, true
FROM products
WHERE sku = 'client_unlock_30days'
ON CONFLICT (product_id, platform) DO NOTHING;

-- 3) Agregar mapeo Google Play para CLIENT_UNLOCK_30 (no existe aún; el de
--    CLIENT_UNLOCK_7 ya tiene uno legacy de un flujo de Google Play Billing
--    directo que no se toca aquí para no romper código existente). Android
--    hoy compra vía navegador externo (Transbank/Mercado Pago, igual que
--    Web) y no vía RevenueCat/Google Play Billing, pero se deja el mapeo
--    listo para cuando se implemente ese flujo nativo en Android.
INSERT INTO platform_products (product_id, platform, platform_product_id, platform_price, is_active)
SELECT id, 'google_play', 'bapp_client_unlock_30', price_clp::text, true
FROM products
WHERE sku = 'client_unlock_30days'
ON CONFLICT (product_id, platform) DO NOTHING;

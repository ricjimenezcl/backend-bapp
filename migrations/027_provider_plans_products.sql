-- ============================================
-- MIGRACIÓN 027: Catálogo completo "Planes para Proveedores"
-- Fecha: 2026-09-27
-- Descripción: Completa el catálogo de productos de proveedor
-- (BAPP-PROVEEDOR-7D/MENSUAL/ANUAL + leads + servicio anual). Estos SKUs
-- ya funcionaban vía Transbank gracias al fallback hardcodeado
-- PRODUCT_TYPE_CONFIG en payments_transbank.py, pero al no existir como
-- `Product` real en BD, el flujo de Mercado Pago (que exige un Product
-- real vía ProductService.get_product_by_sku) fallaba con 404 para todos
-- ellos. `provider_service_30days`/`service_publication_30days` NO se
-- agrega aquí porque ya existe desde la migración 009.
-- ============================================

INSERT INTO products (sku, name, description, target_role, duration_days, price_usd, price_clp, free_limit, product_metadata, is_active) VALUES
(
    'provider_service_1year',
    'Servicio adicional 1 año',
    'Publica un servicio adicional durante 365 días a costo anual preferente',
    'PROVIDER',
    365,
    19.90,
    17990,
    0,
    '{"benefits": ["365 días de publicación", "Mejor costo total frente al mensual", "Escala tu oferta de servicios"]}'::jsonb,
    true
),
(
    'provider_leads_unlock_7days',
    'Leads 7 días',
    'Desbloquea el detalle de clientes interesados en tus servicios durante 7 días',
    'PROVIDER',
    7,
    1.65,
    1490,
    0,
    '{"benefits": ["Ver clientes reales interesados", "Datos de contacto completos", "Activación inmediata"]}'::jsonb,
    true
),
(
    'provider_leads_unlock_30days',
    'Leads 30 días',
    'Desbloquea el detalle de clientes interesados en tus servicios durante 30 días',
    'PROVIDER',
    30,
    5.50,
    4990,
    0,
    '{"benefits": ["Mayor ventana de conversión", "Leads completos por 30 días", "Ideal para captación continua"]}'::jsonb,
    true
),
(
    'provider_premium_monthly',
    'Premium Proveedor mensual',
    'Perfil y herramientas premium para proveedores, con hasta 7 servicios activos',
    'PROVIDER',
    30,
    6.60,
    5990,
    0,
    '{"benefits": ["Perfil premium", "Hasta 7 servicios activos", "Accesos premium completos"]}'::jsonb,
    true
),
(
    'provider_premium_annual',
    'Premium Proveedor anual',
    'Plan anual preferente: perfil y herramientas premium con hasta 7 servicios activos',
    'PROVIDER',
    365,
    55.00,
    49990,
    0,
    '{"benefits": ["Perfil premium todo el año", "Hasta 7 servicios activos", "Mejor costo total frente al mensual"]}'::jsonb,
    true
)
ON CONFLICT (sku) DO NOTHING;

INSERT INTO platform_products (product_id, platform, platform_product_id, platform_price)
SELECT id, 'web', sku || '_web', price_clp::text
FROM products
WHERE sku IN (
    'provider_service_1year',
    'provider_leads_unlock_7days',
    'provider_leads_unlock_30days',
    'provider_premium_monthly',
    'provider_premium_annual'
)
ON CONFLICT (product_id, platform) DO NOTHING;

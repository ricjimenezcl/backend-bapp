-- Migración 029: Planes bundle de proveedor (7 días / Mensual / Anual)
--
-- Reemplaza, para COMPRAS NUEVAS, los 6 productos granulares de proveedor
-- (provider_service_1year, provider_leads_unlock_7days/30days,
-- provider_premium_monthly/annual) por 3 planes bundle que otorgan TODOS
-- los beneficios juntos (premium + hasta 7 servicios activos + leads
-- desbloqueados).
--
-- Los 6 productos anteriores NO se desactivan ni se eliminan: las
-- transacciones históricas que los referencian (FK product_id) deben
-- seguir resolviendo correctamente hasta su expiración natural.

INSERT INTO products (sku, name, description, target_role, duration_days, price_usd, price_clp, free_limit, product_metadata, is_active) VALUES
(
    'provider_plan_7days',
    'Plan Proveedor 7 días',
    'Plan completo de proveedor por 7 días: acceso a leads, publicación de hasta 7 servicios activos y perfil premium',
    'PROVIDER',
    7,
    1.65,
    1490,
    0,
    '{"benefits": ["Acceso a leads y clientes interesados", "Hasta 7 servicios activos", "Perfil y ranking premium"]}'::jsonb,
    true
),
(
    'provider_plan_monthly',
    'Plan Proveedor mensual',
    'Plan completo de proveedor mensual: acceso a leads, publicación de hasta 7 servicios activos y perfil premium',
    'PROVIDER',
    30,
    6.60,
    5990,
    0,
    '{"benefits": ["Acceso a leads y clientes interesados", "Hasta 7 servicios activos", "Perfil y ranking premium"]}'::jsonb,
    true
),
(
    'provider_plan_annual',
    'Plan Proveedor anual',
    'Plan completo de proveedor anual (mejor costo total): acceso a leads, publicación de hasta 7 servicios activos y perfil premium',
    'PROVIDER',
    365,
    55.00,
    49990,
    0,
    '{"benefits": ["Acceso a leads y clientes interesados", "Hasta 7 servicios activos", "Perfil y ranking premium", "Mejor costo total frente al mensual"]}'::jsonb,
    true
)
ON CONFLICT (sku) DO NOTHING;

INSERT INTO platform_products (product_id, platform, platform_product_id, platform_price, is_active)
SELECT id, 'web', sku || '_web', price_clp::text, true
FROM products
WHERE sku IN (
    'provider_plan_7days',
    'provider_plan_monthly',
    'provider_plan_annual'
)
ON CONFLICT (product_id, platform) DO NOTHING;

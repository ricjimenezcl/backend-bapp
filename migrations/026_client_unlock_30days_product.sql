-- ============================================
-- MIGRACIÓN 026: Producto "Acceso Cliente 30 días"
-- Fecha: 2026-09-27
-- Descripción: Completa el catálogo de Acceso Cliente (BAPP-CLIENTE-7D /
-- BAPP-CLIENTE-30D). El producto de 7 días ya existía (premium_access_7days,
-- migración 009). Este producto de 30 días faltaba en la tabla `products`,
-- por lo que el flujo de Mercado Pago (que exige un Product real en BD)
-- fallaba con 404 para CLIENT_UNLOCK_30. Transbank seguía funcionando por el
-- fallback hardcodeado en PRODUCT_TYPE_CONFIG, pero sin fila real asociada.
-- ============================================

INSERT INTO products (sku, name, description, target_role, duration_days, price_usd, price_clp, free_limit, product_metadata) VALUES
(
    'client_unlock_30days',
    'Acceso Cliente 30 días',
    'Desbloquea proveedores y contacta servicios durante 30 días',
    'CLIENT',
    30,
    5.50,
    4990,
    0,
    '{"benefits": ["Acceso a todos los proveedores disponibles", "Contacto sin límites durante la vigencia", "Activación después de confirmar el pago", "Búsqueda por ubicación y categoría"]}'::jsonb
)
ON CONFLICT (sku) DO NOTHING;

INSERT INTO platform_products (product_id, platform, platform_product_id, platform_price) VALUES
((SELECT id FROM products WHERE sku = 'client_unlock_30days'), 'web', 'client_unlock_30days_web', '4990')
ON CONFLICT (product_id, platform) DO NOTHING;

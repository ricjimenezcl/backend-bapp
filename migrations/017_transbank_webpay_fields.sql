-- ============================================
-- MIGRACIÓN 017: Campos Webpay Plus en transactions
-- Fecha: 2026-05-12
-- ============================================

ALTER TABLE transactions
    ADD COLUMN IF NOT EXISTS buy_order VARCHAR(255),
    ADD COLUMN IF NOT EXISTS tbk_token VARCHAR(255),
    ADD COLUMN IF NOT EXISTS authorization_code VARCHAR(50),
    ADD COLUMN IF NOT EXISTS paid_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS product_type VARCHAR(50);

CREATE INDEX IF NOT EXISTS idx_transactions_buy_order ON transactions(buy_order);
CREATE INDEX IF NOT EXISTS idx_transactions_tbk_token ON transactions(tbk_token);
CREATE INDEX IF NOT EXISTS idx_transactions_product_type ON transactions(product_type);

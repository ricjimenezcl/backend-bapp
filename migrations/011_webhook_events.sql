-- ============================================================
-- Migración 011 — Tabla webhook_events
-- Propósito: auditoría e idempotencia para webhooks entrantes
--            de Mercado Pago (y futuros providers).
--
-- Cómo funciona:
--   1. Al recibir un webhook, insertar con ON CONFLICT DO NOTHING.
--   2. Si el INSERT no inserta filas (event_id ya existía), ignorar
--      el evento — es un reintento duplicado de Mercado Pago.
--   3. Procesar la lógica de negocio solo si la inserción tuvo éxito.
--
-- Esto garantiza que cada evento se procese exactamente una vez,
-- incluso si Mercado Pago reintenta la notificación varias veces.
-- ============================================================

CREATE TABLE IF NOT EXISTS webhook_events (
    id              SERIAL PRIMARY KEY,

    -- Identificador único del evento enviado por el provider.
    -- Para Mercado Pago: campo "id" del payload JSON.
    -- UNIQUE garantiza idempotencia a nivel de base de datos.
    event_id        VARCHAR(128)    NOT NULL,

    -- Provider que envió el evento: 'mercadopago' | 'google_play' | 'apple_iap'
    provider        VARCHAR(32)     NOT NULL,

    -- Tipo de evento: 'payment' | 'refund' | 'subscription' | etc.
    event_type      VARCHAR(64),

    -- Momento en que llegó al servidor
    received_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- Si el evento fue procesado correctamente
    processed       BOOLEAN         NOT NULL DEFAULT FALSE,

    -- Momento en que se procesó (NULL si aún no)
    processed_at    TIMESTAMPTZ,

    -- ID de la transacción interna creada/actualizada por este evento
    transaction_id  INTEGER         REFERENCES transactions(id) ON DELETE SET NULL,

    -- Payload completo del webhook para auditoría y debugging
    payload         JSONB,

    -- Error si el procesamiento falló (para reintento manual)
    error_message   TEXT,

    CONSTRAINT uq_webhook_event UNIQUE (provider, event_id)
);

-- Índices para consultas frecuentes
CREATE INDEX IF NOT EXISTS idx_webhook_events_provider_received
    ON webhook_events (provider, received_at DESC);

CREATE INDEX IF NOT EXISTS idx_webhook_events_processed
    ON webhook_events (processed, received_at DESC)
    WHERE processed = FALSE;

CREATE INDEX IF NOT EXISTS idx_webhook_events_transaction_id
    ON webhook_events (transaction_id)
    WHERE transaction_id IS NOT NULL;

COMMENT ON TABLE webhook_events IS
    'Registro de webhooks entrantes para auditoría e idempotencia. '
    'La restricción UNIQUE (provider, event_id) garantiza procesamiento exactamente-una-vez.';

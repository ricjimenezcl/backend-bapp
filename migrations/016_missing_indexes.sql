-- Migration 016: Missing performance indexes
-- Covers FK columns used in frequent JOINs/WHERE that lack explicit indexes.

-- service_providers.service_id (high-frequency JOIN with service_categories)
CREATE INDEX IF NOT EXISTS ix_service_providers_service_id
    ON service_providers (service_id);

-- service_providers.provider_id
CREATE INDEX IF NOT EXISTS ix_service_providers_provider_id
    ON service_providers (provider_id);

-- service_providers.validation_status + is_available (used in every geo query WHERE clause)
CREATE INDEX IF NOT EXISTS ix_service_providers_active_status
    ON service_providers (validation_status, is_available);

-- bookings.status (filtered in almost every booking query)
CREATE INDEX IF NOT EXISTS ix_bookings_status
    ON bookings (status);

-- bookings composite: client + status (list my bookings, filtered)
CREATE INDEX IF NOT EXISTS ix_bookings_client_status
    ON bookings (client_id, status);

-- bookings composite: provider + status (provider dashboard)
CREATE INDEX IF NOT EXISTS ix_bookings_provider_status
    ON bookings (provider_id, status);

-- bookings.scheduled_date (calendar queries)
CREATE INDEX IF NOT EXISTS ix_bookings_scheduled_date
    ON bookings (scheduled_date);

-- users.oauth_id (Google/Facebook login lookup)
CREATE INDEX IF NOT EXISTS ix_users_oauth_id
    ON users (oauth_id)
    WHERE oauth_id IS NOT NULL;

-- providers.run (Chilean RUT lookup on verification)
CREATE INDEX IF NOT EXISTS ix_providers_run
    ON providers (run)
    WHERE run IS NOT NULL;

-- messages.conversation_id + created_at (chat history pagination)
CREATE INDEX IF NOT EXISTS ix_messages_conversation_created
    ON messages (conversation_id, created_at DESC);

-- notifications.user_id + is_read (unread count + list)
CREATE INDEX IF NOT EXISTS ix_notifications_user_unread
    ON notifications (user_id, is_read)
    WHERE is_read = FALSE;

-- reviews.provider_id (rating calculation)
CREATE INDEX IF NOT EXISTS ix_reviews_provider_id
    ON reviews (provider_id);

-- transactions.user_id + status
CREATE INDEX IF NOT EXISTS ix_transactions_user_status
    ON transactions (user_id, status);

DO $$ BEGIN
    RAISE NOTICE 'Migration 016: all missing indexes created.';
END $$;

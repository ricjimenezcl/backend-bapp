-- Migration 014: Align notifications table columns with SQLAlchemy model
-- The table exists but column names differ from the model expectations.
-- Idempotent: uses DO $$ blocks to skip if already done.

DO $$
BEGIN
    -- Rename "type" -> "notification_type"
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'notifications' AND column_name = 'type'
    ) THEN
        ALTER TABLE notifications RENAME COLUMN "type" TO notification_type;
    END IF;

    -- Rename "message" -> "content"
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'notifications' AND column_name = 'message'
    ) THEN
        ALTER TABLE notifications RENAME COLUMN message TO content;
    END IF;

    -- Add related_entity_type if missing
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'notifications' AND column_name = 'related_entity_type'
    ) THEN
        ALTER TABLE notifications ADD COLUMN related_entity_type VARCHAR(50);
    END IF;

    -- Add related_entity_id if missing
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'notifications' AND column_name = 'related_entity_id'
    ) THEN
        ALTER TABLE notifications ADD COLUMN related_entity_id INTEGER;
    END IF;

    -- Add read_at if missing
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'notifications' AND column_name = 'read_at'
    ) THEN
        ALTER TABLE notifications ADD COLUMN read_at TIMESTAMP;
    END IF;

    -- Add updated_at if missing
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'notifications' AND column_name = 'updated_at'
    ) THEN
        ALTER TABLE notifications ADD COLUMN updated_at TIMESTAMP DEFAULT NOW();
    END IF;
END $$;

-- Ensure indexes exist
CREATE INDEX IF NOT EXISTS ix_notifications_user_id          ON notifications(user_id);
CREATE INDEX IF NOT EXISTS ix_notifications_notification_type ON notifications(notification_type);
CREATE INDEX IF NOT EXISTS ix_notifications_is_read           ON notifications(is_read);
CREATE INDEX IF NOT EXISTS ix_notifications_created_at        ON notifications(created_at);

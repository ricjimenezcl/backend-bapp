-- migrations/add_chat_system.sql
-- Chat System: Conversations, Messages, Message Status
-- Supports 1:1 and group conversations

DO $$ BEGIN
    CREATE TYPE conversation_type_enum AS ENUM ('direct', 'group');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;
CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY,
    conversation_type conversation_type_enum NOT NULL DEFAULT 'direct',
    title VARCHAR(255),
    description TEXT,
    created_by_id INTEGER NOT NULL,
    last_message_id UUID,
    last_message_at TIMESTAMP,
    last_message_preview VARCHAR(500),
    is_archived BOOLEAN DEFAULT FALSE,
    archived_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_conversations_created_by FOREIGN KEY (created_by_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_created_by_id ON conversations(created_by_id);
CREATE INDEX IF NOT EXISTS idx_last_message_at ON conversations(last_message_at);
CREATE INDEX IF NOT EXISTS idx_is_archived ON conversations(is_archived);
CREATE INDEX IF NOT EXISTS idx_created_at ON conversations(created_at);

CREATE TABLE IF NOT EXISTS conversation_participants (
    id UUID PRIMARY KEY,
    conversation_id UUID NOT NULL,
    user_id INTEGER NOT NULL,
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    left_at TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    last_read_message_id UUID,
    last_read_at TIMESTAMP,
    muted BOOLEAN DEFAULT FALSE,
    pinned BOOLEAN DEFAULT FALSE,
    CONSTRAINT unique_conversation_user UNIQUE (conversation_id, user_id),
    CONSTRAINT fk_conv_part_conversation FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
    CONSTRAINT fk_conv_part_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_user_id ON conversation_participants(user_id);
CREATE INDEX IF NOT EXISTS idx_is_active ON conversation_participants(is_active);
CREATE INDEX IF NOT EXISTS idx_pinned ON conversation_participants(pinned);

DO $$ BEGIN
    CREATE TYPE message_content_type_enum AS ENUM ('text', 'image', 'file', 'video', 'audio');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;
DO $$ BEGIN
    CREATE TYPE message_status_enum AS ENUM ('pending', 'sent', 'delivered', 'read');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;
CREATE TABLE IF NOT EXISTS messages (
    id UUID PRIMARY KEY,
    conversation_id UUID NOT NULL,
    sender_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    content_type message_content_type_enum DEFAULT 'text',
    attachment_url VARCHAR(500),
    attachment_cloudinary_id VARCHAR(255),
    attachment_size INTEGER,
    attachment_mimetype VARCHAR(100),
    attachment_metadata JSON,
    is_edited BOOLEAN DEFAULT FALSE,
    edited_at TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMP,
    status message_status_enum DEFAULT 'pending',
    reply_to_message_id UUID,
    reactions JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_messages_conversation FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
    CONSTRAINT fk_messages_sender FOREIGN KEY (sender_id) REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT fk_messages_reply FOREIGN KEY (reply_to_message_id) REFERENCES messages(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_conversation_id ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_sender_id ON messages(sender_id);
CREATE INDEX IF NOT EXISTS idx_created_at ON messages(created_at);
CREATE INDEX IF NOT EXISTS idx_is_deleted ON messages(is_deleted);
CREATE INDEX IF NOT EXISTS idx_reply_to ON messages(reply_to_message_id);
CREATE INDEX IF NOT EXISTS idx_status ON messages(status);

CREATE TYPE msg_status_enum AS ENUM ('sent', 'delivered', 'read');
CREATE TABLE IF NOT EXISTS message_status (
    id UUID PRIMARY KEY,
    message_id UUID NOT NULL,
    user_id INTEGER NOT NULL,
    delivered_at TIMESTAMP,
    read_at TIMESTAMP,
    status msg_status_enum DEFAULT 'sent',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_message_user UNIQUE (message_id, user_id),
    CONSTRAINT fk_msg_status_message FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
    CONSTRAINT fk_msg_status_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_user_id ON message_status(user_id);
CREATE INDEX IF NOT EXISTS idx_status ON message_status(status);
CREATE INDEX IF NOT EXISTS idx_read_at ON message_status(read_at);

CREATE TYPE invitation_status_enum AS ENUM ('pending', 'accepted', 'declined', 'cancelled');
CREATE TABLE IF NOT EXISTS conversation_invitations (
    id UUID PRIMARY KEY,
    conversation_id UUID NOT NULL,
    invited_by_id INTEGER NOT NULL,
    invited_user_id INTEGER NOT NULL,
    status invitation_status_enum DEFAULT 'pending',
    accepted_at TIMESTAMP,
    declined_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_invitation UNIQUE (conversation_id, invited_user_id),
    CONSTRAINT fk_inv_conversation FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
    CONSTRAINT fk_inv_invited_by FOREIGN KEY (invited_by_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_inv_invited_user FOREIGN KEY (invited_user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_invited_user_id ON conversation_invitations(invited_user_id);
CREATE INDEX IF NOT EXISTS idx_status ON conversation_invitations(status);

CREATE TABLE IF NOT EXISTS conversation_blocks (
    id UUID PRIMARY KEY,
    conversation_id UUID,
    blocked_user_id INTEGER NOT NULL,
    blocker_user_id INTEGER NOT NULL,
    reason VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_block UNIQUE (conversation_id, blocked_user_id, blocker_user_id),
    CONSTRAINT fk_block_conversation FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
    CONSTRAINT fk_block_blocked_user FOREIGN KEY (blocked_user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_block_blocker_user FOREIGN KEY (blocker_user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_blocked_user_id ON conversation_blocks(blocked_user_id);
CREATE INDEX IF NOT EXISTS idx_blocker_user_id ON conversation_blocks(blocker_user_id);

CREATE TABLE IF NOT EXISTS message_search_index (
    id UUID PRIMARY KEY,
    message_id UUID NOT NULL UNIQUE,
    conversation_id UUID NOT NULL,
    sender_id INTEGER NOT NULL,
    content_vector TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_search_message FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
    CONSTRAINT fk_search_conversation FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_conversation_id ON message_search_index(conversation_id);
CREATE INDEX IF NOT EXISTS ft_content_vector ON message_search_index USING GIN (to_tsvector('spanish', content_vector));

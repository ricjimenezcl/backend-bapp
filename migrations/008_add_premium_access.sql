-- Migration: Add Premium Access Control to Users
-- Date: 2026-03-08
-- Description: Adds premium subscription fields to users table for access control

-- Add premium access columns
ALTER TABLE users 
ADD COLUMN has_premium BOOLEAN DEFAULT FALSE NOT NULL,
ADD COLUMN premium_activated_at TIMESTAMP NULL,
ADD COLUMN premium_expires_at TIMESTAMP NULL;

-- Create index for premium queries (fast lookup)
CREATE INDEX idx_users_premium_active ON users(has_premium, premium_expires_at)
WHERE has_premium = TRUE;

-- Add comment for documentation
COMMENT ON COLUMN users.has_premium IS 'Indicates if user has active premium subscription';
COMMENT ON COLUMN users.premium_activated_at IS 'Timestamp when premium was activated';
COMMENT ON COLUMN users.premium_expires_at IS 'Timestamp when premium expires (7 days from activation)';

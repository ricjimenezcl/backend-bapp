-- Migration 010: Add email verification columns to users table
-- Run once on the production database

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS email_verification_token VARCHAR(128),
    ADD COLUMN IF NOT EXISTS email_verification_expiration TIMESTAMP;

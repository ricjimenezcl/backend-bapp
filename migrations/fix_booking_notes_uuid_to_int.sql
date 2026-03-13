-- Fix BookingNote table UUID columns to Integer
-- Migration: Convert booking_notes table ID columns from UUID to Integer

BEGIN;

-- Drop the booking_notes table if it exists (to recreate with correct types)
DROP TABLE IF EXISTS booking_notes CASCADE;

-- Create booking_notes with correct Integer types
CREATE TABLE booking_notes (
    id SERIAL PRIMARY KEY,
    booking_id INTEGER NOT NULL,
    note_type VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    created_by_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_booking_notes_booking_id FOREIGN KEY (booking_id) REFERENCES bookings(id) ON DELETE CASCADE,
    CONSTRAINT fk_booking_notes_created_by_id FOREIGN KEY (created_by_id) REFERENCES users(id) ON DELETE SET NULL
);

-- Create indices
CREATE INDEX idx_booking_notes_booking_id ON booking_notes(booking_id);
CREATE INDEX idx_booking_notes_created_at ON booking_notes(created_at);

COMMIT;

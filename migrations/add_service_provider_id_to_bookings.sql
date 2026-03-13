ALTER TABLE bookings ADD COLUMN service_provider_id INTEGER REFERENCES service_providers(id);
CREATE INDEX idx_bookings_service_provider_id ON bookings(service_provider_id);
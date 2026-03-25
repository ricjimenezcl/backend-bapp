-- Expand icon column in main_categories and service_categories
-- to support Cloudinary URLs (previously String(50) was too short)

ALTER TABLE main_categories    ALTER COLUMN icon TYPE VARCHAR(500);
ALTER TABLE service_categories ALTER COLUMN icon TYPE VARCHAR(500);

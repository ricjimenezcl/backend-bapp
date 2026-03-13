-- Migration: Add Document Verification System
-- Date: 2026-01-27
-- Description: Add document upload and face verification tables for provider identity verification

-- ============================================================
-- TABLE: user_documents
-- Purpose: Store all uploaded documents (ID, selfie, etc)
-- ============================================================
CREATE TABLE IF NOT EXISTS user_documents (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL,
    document_type ENUM('IDENTITY_DOCUMENT', 'SELFIE', 'BACKGROUND_CHECK') NOT NULL,
    cloudinary_url VARCHAR(500) NOT NULL,
    cloudinary_public_id VARCHAR(255) UNIQUE,
    file_size INT,
    mime_type VARCHAR(50),
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NULL,
    
    CONSTRAINT fk_user_documents_user FOREIGN KEY (user_id) 
        REFERENCES users(id) ON DELETE CASCADE,
    
    INDEX idx_user_id (user_id),
    INDEX idx_document_type (document_type),
    INDEX idx_uploaded_at (uploaded_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================
-- TABLE: provider_verification
-- Purpose: Track face matching and identity verification status
-- ============================================================
CREATE TABLE IF NOT EXISTS provider_verification (
    id INT PRIMARY KEY AUTO_INCREMENT,
    provider_id INT NOT NULL UNIQUE,
    selfie_document_id INT NOT NULL,
    id_document_id INT NOT NULL,
    
    -- Face matching results
    face_match_score DECIMAL(5, 2) DEFAULT 0.00,  -- 0-100 confidence score
    face_match_status ENUM(
        'PENDING',           -- Waiting for verification
        'PROCESSING',        -- AI processing face match
        'APPROVED',          -- Faces match and admin approved
        'REJECTED',          -- Faces don't match or admin rejected
        'EXPIRED'            -- Verification expired, needs renewal
    ) DEFAULT 'PENDING',
    
    -- Admin verification
    verified_by_admin_id INT,
    admin_verification_date TIMESTAMP NULL,
    admin_notes TEXT,
    
    -- OCR results from ID document
    ocr_extracted_name VARCHAR(255),
    ocr_extracted_id VARCHAR(50),
    ocr_confidence DECIMAL(5, 2),
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    CONSTRAINT fk_provider_verification_provider 
        FOREIGN KEY (provider_id) 
        REFERENCES service_providers(id) ON DELETE CASCADE,
    
    CONSTRAINT fk_provider_verification_selfie 
        FOREIGN KEY (selfie_document_id) 
        REFERENCES user_documents(id),
    
    CONSTRAINT fk_provider_verification_id 
        FOREIGN KEY (id_document_id) 
        REFERENCES user_documents(id),
    
    CONSTRAINT fk_provider_verification_admin 
        FOREIGN KEY (verified_by_admin_id) 
        REFERENCES users(id) ON DELETE SET NULL,
    
    INDEX idx_provider_id (provider_id),
    INDEX idx_face_match_status (face_match_status),
    INDEX idx_admin_verification_date (admin_verification_date),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================
-- TABLE: galleries
-- Purpose: Store provider gallery images (from Cloudinary)
-- ============================================================
CREATE TABLE IF NOT EXISTS galleries (
    id INT PRIMARY KEY AUTO_INCREMENT,
    provider_id INT NOT NULL,
    cloudinary_url VARCHAR(500) NOT NULL,
    cloudinary_public_id VARCHAR(255) UNIQUE,
    caption VARCHAR(255),
    display_order INT DEFAULT 0,
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT fk_galleries_provider 
        FOREIGN KEY (provider_id) 
        REFERENCES service_providers(id) ON DELETE CASCADE,
    
    INDEX idx_provider_id (provider_id),
    INDEX idx_display_order (display_order)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================
-- MODIFY service_providers TABLE
-- Add verification requirement field
-- ============================================================
ALTER TABLE service_providers ADD COLUMN IF NOT EXISTS 
    requires_verification_update BOOLEAN DEFAULT FALSE 
    COMMENT 'Flag to indicate documents need refresh/renewal'
    AFTER validation_status;

-- ============================================================
-- CREATE INDEX for performance optimization
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_service_providers_user_id_status 
    ON service_providers(user_id, validation_status);

-- ============================================================
-- Add comment to service_providers about verification requirement
-- ============================================================
ALTER TABLE service_providers MODIFY COLUMN validation_status 
    ENUM("pending", "approved", "rejected") DEFAULT "pending"
    COMMENT 'Provider can only add services when validation_status=approved AND provider_verification.face_match_status=approved';

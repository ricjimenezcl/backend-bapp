-- ============================================================================
-- BAPP - Sistema de Reportes y Moderación de Contenido
-- Migración de Base de Datos
-- ============================================================================
-- 
-- Descripción:
--   Agrega 3 nuevas tablas al sistema BAPP:
--   1. reports - Reportes de contenido inapropiado
--   2. blocked_words - Palabras prohibidas para validación
--   3. moderation_history - Historial de acciones de moderación
--
-- Instrucciones:
--   psql -U tu_usuario -d bapp_db -f migrations/add_reports_system.sql
--
-- ============================================================================

BEGIN;

-- ============================================================================
-- Tabla: reports
-- Descripción: Almacena reportes de contenido inapropiado
-- ============================================================================

CREATE TABLE IF NOT EXISTS reports (
    id SERIAL PRIMARY KEY,
    
    -- Tipo de reporte
    report_type VARCHAR(50) NOT NULL CHECK (report_type IN (
        'INAPPROPRIATE_CONTENT',
        'FAKE_PROFILE',
        'HARASSMENT',
        'SPAM',
        'FRAUD',
        'HATE_SPEECH',
        'VIOLENCE',
        'NUDITY',
        'INTELLECTUAL_PROPERTY',
        'OTHER'
    )),
    
    -- Entidad reportada (genérico)
    reported_entity_type VARCHAR(50) NOT NULL CHECK (reported_entity_type IN (
        'USER',
        'REVIEW',
        'SERVICE',
        'CHAT_MESSAGE'
    )),
    reported_entity_id INTEGER NOT NULL,
    
    -- Usuario reportante
    reporter_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- Usuario reportado (si aplica)
    reported_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    
    -- Detalles del reporte
    description TEXT,
    evidence_urls JSON,
    
    -- Estado del reporte
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING' CHECK (status IN (
        'PENDING',
        'UNDER_REVIEW',
        'RESOLVED',
        'DISMISSED',
        'ESCALATED'
    )),
    
    -- Revisión (moderador)
    reviewed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at TIMESTAMP,
    review_notes TEXT,
    
    -- Acción tomada
    action_taken VARCHAR(50) CHECK (action_taken IN (
        'NO_ACTION',
        'WARNING',
        'CONTENT_REMOVED',
        'TEMPORARY_SUSPENSION',
        'PERMANENT_BAN',
        'ACCOUNT_DELETED'
    )),
    action_details TEXT,
    
    -- Timestamps
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Índices para reports
CREATE INDEX idx_reports_type ON reports(report_type);
CREATE INDEX idx_reports_entity_type ON reports(reported_entity_type);
CREATE INDEX idx_reports_entity ON reports(reported_entity_type, reported_entity_id);
CREATE INDEX idx_reports_reporter ON reports(reporter_id);
CREATE INDEX idx_reports_reported_user ON reports(reported_user_id);
CREATE INDEX idx_reports_status ON reports(status);
CREATE INDEX idx_reports_created_at ON reports(created_at DESC);

-- Comentarios
COMMENT ON TABLE reports IS 'Reportes de contenido inapropiado';
COMMENT ON COLUMN reports.report_type IS 'Tipo de reporte (HARASSMENT, SPAM, FRAUD, etc.)';
COMMENT ON COLUMN reports.reported_entity_type IS 'Tipo de entidad reportada (USER, REVIEW, SERVICE, CHAT_MESSAGE)';
COMMENT ON COLUMN reports.reported_entity_id IS 'ID de la entidad reportada';
COMMENT ON COLUMN reports.evidence_urls IS 'URLs de capturas de pantalla u otra evidencia (JSON array)';


-- ============================================================================
-- Tabla: blocked_words
-- Descripción: Lista de palabras prohibidas para moderación de contenido
-- ============================================================================

CREATE TABLE IF NOT EXISTS blocked_words (
    id SERIAL PRIMARY KEY,
    
    -- Palabra bloqueada
    word VARCHAR(255) NOT NULL UNIQUE,
    
    -- Patrón regex opcional (para variaciones)
    pattern VARCHAR(500),
    
    -- Categoría
    category VARCHAR(20) NOT NULL CHECK (category IN (
        'SEXUAL',
        'DRUGS',
        'VIOLENCE',
        'HATE',
        'FRAUD',
        'SPAM'
    )),
    
    -- Severidad
    severity VARCHAR(10) NOT NULL CHECK (severity IN (
        'LOW',
        'MEDIUM',
        'HIGH',
        'CRITICAL'
    )),
    
    -- Idioma (ISO 639-1)
    language VARCHAR(2) NOT NULL DEFAULT 'es',
    
    -- Estado
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    
    -- Auditoría
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    created_by INTEGER,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Índices para blocked_words
CREATE INDEX idx_blocked_words_category ON blocked_words(category);
CREATE INDEX idx_blocked_words_severity ON blocked_words(severity);
CREATE INDEX idx_blocked_words_language ON blocked_words(language);
CREATE INDEX idx_blocked_words_active ON blocked_words(is_active);
CREATE INDEX idx_blocked_words_word_lower ON blocked_words(LOWER(word));

-- Comentarios
COMMENT ON TABLE blocked_words IS 'Palabras prohibidas para validación de contenido';
COMMENT ON COLUMN blocked_words.word IS 'Palabra o frase bloqueada (almacenada en lowercase)';
COMMENT ON COLUMN blocked_words.pattern IS 'Patrón regex opcional para variaciones';
COMMENT ON COLUMN blocked_words.category IS 'Categoría de la palabra (SEXUAL, VIOLENCE, etc.)';
COMMENT ON COLUMN blocked_words.severity IS 'Severidad (LOW, MEDIUM, HIGH, CRITICAL)';


-- ============================================================================
-- Tabla: moderation_history
-- Descripción: Historial de acciones de moderación
-- ============================================================================

CREATE TABLE IF NOT EXISTS moderation_history (
    id SERIAL PRIMARY KEY,
    
    -- Tipo de acción
    moderation_type VARCHAR(50) NOT NULL CHECK (moderation_type IN (
        'USER_SUSPENDED',
        'USER_BANNED',
        'USER_WARNING',
        'USER_REINSTATED',
        'CONTENT_REMOVED',
        'CONTENT_APPROVED',
        'REPORT_RESOLVED',
        'REPORT_DISMISSED'
    )),
    
    -- Usuario afectado
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- Moderador
    moderator_id INTEGER NOT NULL REFERENCES users(id) ON DELETE SET NULL,
    
    -- Reporte relacionado (si aplica)
    report_id INTEGER REFERENCES reports(id) ON DELETE SET NULL,
    
    -- Razón y detalles
    reason TEXT NOT NULL,
    details JSON,
    
    -- Duración (para suspensiones temporales, en días)
    duration_days INTEGER,
    
    -- Timestamp
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Índices para moderation_history
CREATE INDEX idx_moderation_history_user ON moderation_history(user_id);
CREATE INDEX idx_moderation_history_moderator ON moderation_history(moderator_id);
CREATE INDEX idx_moderation_history_report ON moderation_history(report_id);
CREATE INDEX idx_moderation_history_type ON moderation_history(moderation_type);
CREATE INDEX idx_moderation_history_created ON moderation_history(created_at DESC);

-- Comentarios
COMMENT ON TABLE moderation_history IS 'Historial de acciones de moderación para auditoría';
COMMENT ON COLUMN moderation_history.moderation_type IS 'Tipo de acción (USER_SUSPENDED, USER_BANNED, etc.)';
COMMENT ON COLUMN moderation_history.reason IS 'Razón de la acción de moderación';
COMMENT ON COLUMN moderation_history.details IS 'Detalles adicionales en formato JSON';


-- ============================================================================
-- Trigger: Actualizar updated_at en reports
-- ============================================================================

CREATE OR REPLACE FUNCTION update_reports_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_reports_updated_at
    BEFORE UPDATE ON reports
    FOR EACH ROW
    EXECUTE FUNCTION update_reports_updated_at();


-- ============================================================================
-- Trigger: Actualizar updated_at en blocked_words
-- ============================================================================

CREATE OR REPLACE FUNCTION update_blocked_words_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_blocked_words_updated_at
    BEFORE UPDATE ON blocked_words
    FOR EACH ROW
    EXECUTE FUNCTION update_blocked_words_updated_at();


-- ============================================================================
-- Verificar resultado
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '✅ Migración completada exitosamente';
    RAISE NOTICE '   - Tabla reports creada';
    RAISE NOTICE '   - Tabla blocked_words creada';
    RAISE NOTICE '   - Tabla moderation_history creada';
    RAISE NOTICE '   - Índices y triggers creados';
    RAISE NOTICE '';
    RAISE NOTICE '📝 Próximos pasos:';
    RAISE NOTICE '   1. Ejecutar seed de palabras: python -m app.scripts.seed_blocked_words';
    RAISE NOTICE '   2. Verificar tablas: \dt reports blocked_words moderation_history';
    RAISE NOTICE '   3. Reiniciar backend';
END $$;

COMMIT;

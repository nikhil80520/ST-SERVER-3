-- ============================================================================
-- PostgreSQL Database Schema for STS-Server
-- Version: 1.0.0
-- Generated from: database_schema.md
-- ============================================================================

-- Enable UUID extension (if needed for future use)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================================
-- TABLE: users (Parent/User Accounts)
-- ============================================================================

CREATE TABLE IF NOT EXISTS users (
    -- Primary Key
    user_id VARCHAR NOT NULL PRIMARY KEY,
    
    -- Parent Information
    parent_name VARCHAR,
    parent_email VARCHAR NOT NULL UNIQUE,
    parent_phone_number VARCHAR,
    
    -- Avatar Configuration
    avatar_seed VARCHAR,
    avatar_style VARCHAR NOT NULL DEFAULT 'adventurer',
    avatar_url VARCHAR,
    avatar_generated BOOLEAN NOT NULL DEFAULT FALSE,
    avatar_updated_at TIMESTAMP WITH TIME ZONE,
    
    -- Counts
    children_count INTEGER NOT NULL DEFAULT 0,
    default_child_id VARCHAR,
    story_count INTEGER NOT NULL DEFAULT 0,
    reference_images_count INTEGER NOT NULL DEFAULT 0,
    
    -- Account Status
    account_status VARCHAR NOT NULL DEFAULT 'trial_active',
    account_status_data JSONB,
    
    -- Activity Tracking
    last_active TIMESTAMP WITH TIME ZONE,
    
    -- Audit Fields
    created_by VARCHAR,
    updated_by VARCHAR,
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT chk_children_count CHECK (children_count >= 0)
);

-- Indexes for users table
CREATE INDEX IF NOT EXISTS idx_users_email ON users(parent_email);
CREATE INDEX IF NOT EXISTS idx_users_created_at ON users(created_at);
CREATE INDEX IF NOT EXISTS idx_users_last_active ON users(last_active);

-- ============================================================================
-- TABLE: voice_clones (Cartesia Voice Clones)
-- ============================================================================

CREATE TABLE IF NOT EXISTS voice_clones (
    -- Primary Key
    voice_clone_id VARCHAR NOT NULL PRIMARY KEY,
    
    -- Foreign Key to User
    user_id VARCHAR NOT NULL,
    
    -- Voice Clone Information
    name VARCHAR NOT NULL,
    description TEXT,
    language VARCHAR NOT NULL DEFAULT 'en',
    
    -- Cartesia Integration
    cartesia_voice_id VARCHAR NOT NULL UNIQUE,
    sample_audio_url VARCHAR,
    
    -- Status
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by VARCHAR,
    updated_by VARCHAR,
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    
    -- Foreign Key Constraint
    CONSTRAINT fk_voice_clones_user 
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- Indexes for voice_clones table
CREATE INDEX IF NOT EXISTS idx_voice_clones_user_id ON voice_clones(user_id);
CREATE INDEX IF NOT EXISTS idx_voice_clones_cartesia_id ON voice_clones(cartesia_voice_id);
CREATE INDEX IF NOT EXISTS idx_voice_clones_created_at ON voice_clones(created_at);

-- ============================================================================
-- TABLE: children (Children Profiles)
-- ============================================================================

CREATE TABLE IF NOT EXISTS children (
    -- Primary Key
    child_id VARCHAR NOT NULL PRIMARY KEY,
    
    -- Foreign Key to User
    user_id VARCHAR NOT NULL,
    
    -- Child Information
    name VARCHAR NOT NULL,
    age INTEGER NOT NULL,
    interests VARCHAR[],
    
    -- Avatar/Image
    image_url VARCHAR,
    avatar_seed VARCHAR,
    avatar_style VARCHAR,
    avatar_url VARCHAR,
    
    -- System Configuration
    system_prompt TEXT,
    
    -- Voice Clone
    voice_clone_id VARCHAR,
    
    -- Status
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    
    -- Audit Fields
    created_by VARCHAR,
    updated_by VARCHAR,
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT chk_age_positive CHECK (age > 0 AND age < 18),
    
    -- Foreign Key Constraints
    CONSTRAINT fk_children_user 
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    CONSTRAINT fk_children_voice_clone 
        FOREIGN KEY (voice_clone_id) REFERENCES voice_clones(voice_clone_id) ON DELETE SET NULL
);

-- Indexes for children table
CREATE INDEX IF NOT EXISTS idx_children_user_id ON children(user_id);
CREATE INDEX IF NOT EXISTS idx_children_voice_clone_id ON children(voice_clone_id);
CREATE INDEX IF NOT EXISTS idx_children_user_active ON children(user_id, is_active);
CREATE INDEX IF NOT EXISTS idx_children_created_at ON children(created_at);

-- ============================================================================
-- TABLE: stories (Generated Stories)
-- ============================================================================

CREATE TABLE IF NOT EXISTS stories (
    -- Primary Key
    story_id VARCHAR NOT NULL PRIMARY KEY,
    
    -- Foreign Keys
    user_id VARCHAR NOT NULL,
    child_id VARCHAR,
    
    -- Story Content
    title VARCHAR NOT NULL,
    user_prompt TEXT,
    status VARCHAR NOT NULL DEFAULT 'pending',
    
    -- Story Data (JSONB)
    child_snapshot JSONB,
    manifest JSONB,
    scenes_data JSONB,
    
    -- Media URLs
    audio_urls VARCHAR[],
    thumbnail_url VARCHAR,
    
    -- Sharing Configuration
    is_shareable BOOLEAN NOT NULL DEFAULT FALSE,
    share_token VARCHAR UNIQUE,
    share_expires_at TIMESTAMP WITH TIME ZONE,
    
    -- Analytics
    view_count INTEGER NOT NULL DEFAULT 0,
    access_log JSONB,
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    
    -- Audit Fields
    created_by VARCHAR,
    updated_by VARCHAR,
    
    -- Constraints
    CONSTRAINT chk_view_count CHECK (view_count >= 0),
    
    -- Foreign Key Constraints
    CONSTRAINT fk_stories_user 
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    CONSTRAINT fk_stories_child 
        FOREIGN KEY (child_id) REFERENCES children(child_id) ON DELETE SET NULL
);

-- Indexes for stories table
CREATE INDEX IF NOT EXISTS idx_stories_user_id ON stories(user_id);
CREATE INDEX IF NOT EXISTS idx_stories_child_id ON stories(child_id);
CREATE INDEX IF NOT EXISTS idx_stories_share_token ON stories(share_token);
CREATE INDEX IF NOT EXISTS idx_stories_user_child ON stories(user_id, child_id);
CREATE INDEX IF NOT EXISTS idx_stories_shareable_views ON stories(is_shareable, view_count);
CREATE INDEX IF NOT EXISTS idx_stories_created_at ON stories(created_at);

-- ============================================================================
-- TABLE: story_shares (Story Sharing Junction Table)
-- ============================================================================

CREATE TABLE IF NOT EXISTS story_shares (
    -- Primary Key (SERIAL auto-increment)
    story_share_id SERIAL PRIMARY KEY,
    
    -- Foreign Keys
    story_id VARCHAR NOT NULL,
    owner_user_id VARCHAR NOT NULL,
    shared_with_user_id VARCHAR NOT NULL,
    
    -- Sharing Metadata
    shared_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    access_token VARCHAR,
    expires_at TIMESTAMP WITH TIME ZONE,
    
    -- Access Tracking
    viewed BOOLEAN NOT NULL DEFAULT FALSE,
    view_count INTEGER NOT NULL DEFAULT 0,
    last_viewed_at TIMESTAMP WITH TIME ZONE,
    
    -- Audit Fields
    created_by VARCHAR,
    updated_by VARCHAR,
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    
    -- Unique Constraint (prevent duplicate shares)
    CONSTRAINT uq_story_share UNIQUE (story_id, shared_with_user_id),
    
    -- Foreign Key Constraints
    CONSTRAINT fk_story_shares_story 
        FOREIGN KEY (story_id) REFERENCES stories(story_id) ON DELETE CASCADE,
    CONSTRAINT fk_story_shares_owner 
        FOREIGN KEY (owner_user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    CONSTRAINT fk_story_shares_recipient 
        FOREIGN KEY (shared_with_user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- Indexes for story_shares table
CREATE INDEX IF NOT EXISTS idx_story_shares_story_id ON story_shares(story_id);
CREATE INDEX IF NOT EXISTS idx_story_shares_owner_id ON story_shares(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_story_shares_recipient_id ON story_shares(shared_with_user_id);

-- ============================================================================
-- TABLE: reference_images (User-Uploaded Reference Images)
-- ============================================================================

CREATE TABLE IF NOT EXISTS reference_images (
    -- Primary Key
    reference_image_id VARCHAR NOT NULL PRIMARY KEY,
    
    -- Foreign Key to User
    user_id VARCHAR NOT NULL,
    
    -- Image Information
    image_url VARCHAR NOT NULL,
    storage_path VARCHAR,
    description TEXT,
    
    -- File Metadata
    file_size INTEGER,
    mime_type VARCHAR,
    
    -- Audit Fields
    created_by VARCHAR,
    updated_by VARCHAR,
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    
    -- Foreign Key Constraint
    CONSTRAINT fk_reference_images_user 
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- Indexes for reference_images table
CREATE INDEX IF NOT EXISTS idx_reference_images_user_id ON reference_images(user_id);
CREATE INDEX IF NOT EXISTS idx_reference_images_created_at ON reference_images(created_at);

-- ============================================================================
-- TABLE: iot_devices (ESP32 and IoT Devices)
-- ============================================================================

CREATE TABLE IF NOT EXISTS iot_devices (
    -- Primary Key
    iot_device_id VARCHAR NOT NULL PRIMARY KEY,
    
    -- Device Information
    device_type VARCHAR NOT NULL,
    device_name VARCHAR,
    firmware_version VARCHAR,
    
    -- Security
    device_secret_hash VARCHAR,
    claim_token VARCHAR UNIQUE,
    claim_token_expires TIMESTAMP WITH TIME ZONE,
    
    -- Ownership
    claimed_by_user_id VARCHAR,
    claimed_at TIMESTAMP WITH TIME ZONE,
    
    -- Status
    status VARCHAR NOT NULL DEFAULT 'unclaimed',
    last_seen_at TIMESTAMP WITH TIME ZONE,
    
    -- Metadata
    metadata JSONB,
    
    -- Audit Fields
    created_by VARCHAR,
    updated_by VARCHAR,
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    
    -- Foreign Key Constraint
    CONSTRAINT fk_iot_devices_user 
        FOREIGN KEY (claimed_by_user_id) REFERENCES users(user_id) ON DELETE SET NULL
);

-- Indexes for iot_devices table
CREATE INDEX IF NOT EXISTS idx_iot_devices_claimed_by ON iot_devices(claimed_by_user_id);
CREATE INDEX IF NOT EXISTS idx_iot_devices_claim_token ON iot_devices(claim_token);
CREATE INDEX IF NOT EXISTS idx_iot_devices_created_at ON iot_devices(created_at);

-- ============================================================================
-- TABLE: password_reset_otps (Password Reset OTP Tokens)
-- ============================================================================

CREATE TABLE IF NOT EXISTS password_reset_otps (
    -- Primary Key (SERIAL auto-increment)
    password_reset_otp_id SERIAL PRIMARY KEY,
    
    -- User Identification
    email VARCHAR NOT NULL,
    user_id VARCHAR,
    
    -- OTP Information
    otp_hash VARCHAR NOT NULL,
    used BOOLEAN NOT NULL DEFAULT FALSE,
    attempts INTEGER NOT NULL DEFAULT 0,
    
    -- Audit Fields
    created_by VARCHAR,
    updated_by VARCHAR,
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    used_at TIMESTAMP WITH TIME ZONE
);

-- Indexes for password_reset_otps table
CREATE INDEX IF NOT EXISTS idx_password_reset_email ON password_reset_otps(email);
CREATE INDEX IF NOT EXISTS idx_password_reset_email_used ON password_reset_otps(email, used);
CREATE INDEX IF NOT EXISTS idx_password_reset_expires_at ON password_reset_otps(expires_at);

-- ============================================================================
-- TABLE: user_activities (User Activity Tracking - Optional)
-- ============================================================================

CREATE TABLE IF NOT EXISTS user_activities (
    -- Primary Key (SERIAL auto-increment)
    user_activity_id SERIAL PRIMARY KEY,
    
    -- Foreign Key to User
    user_id VARCHAR NOT NULL,
    
    -- Activity Information
    activity_type VARCHAR NOT NULL,
    activity_data JSONB,
    
    -- Request Metadata
    ip_address VARCHAR,
    user_agent VARCHAR,
    
    -- Audit Fields
    created_by VARCHAR,
    updated_by VARCHAR,
    
    -- Timestamp
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    
    -- Foreign Key Constraint
    CONSTRAINT fk_user_activities_user 
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- Indexes for user_activities table
CREATE INDEX IF NOT EXISTS idx_user_activities_user_id ON user_activities(user_id);
CREATE INDEX IF NOT EXISTS idx_user_activities_user_type ON user_activities(user_id, activity_type);
CREATE INDEX IF NOT EXISTS idx_user_activities_created_at ON user_activities(created_at);

-- ============================================================================
-- TRIGGERS: Auto-update updated_at timestamp
-- ============================================================================

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply trigger to all tables with updated_at column
CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_children_updated_at BEFORE UPDATE ON children
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_stories_updated_at BEFORE UPDATE ON stories
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_reference_images_updated_at BEFORE UPDATE ON reference_images
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_voice_clones_updated_at BEFORE UPDATE ON voice_clones
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_iot_devices_updated_at BEFORE UPDATE ON iot_devices
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_story_shares_updated_at BEFORE UPDATE ON story_shares
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_password_reset_otps_updated_at BEFORE UPDATE ON password_reset_otps
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_user_activities_updated_at BEFORE UPDATE ON user_activities
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- VERIFICATION QUERIES
-- ============================================================================

-- List all tables
-- SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;

-- Show table sizes
-- SELECT 
--     schemaname,
--     tablename,
--     pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
-- FROM pg_tables
-- WHERE schemaname = 'public'
-- ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;

-- Show all foreign key relationships
-- SELECT
--     tc.table_name, 
--     kcu.column_name, 
--     ccu.table_name AS foreign_table_name,
--     ccu.column_name AS foreign_column_name,
--     rc.delete_rule
-- FROM information_schema.table_constraints AS tc 
-- JOIN information_schema.key_column_usage AS kcu
--   ON tc.constraint_name = kcu.constraint_name
-- JOIN information_schema.constraint_column_usage AS ccu
--   ON ccu.constraint_name = tc.constraint_name
-- JOIN information_schema.referential_constraints AS rc
--   ON tc.constraint_name = rc.constraint_name
-- WHERE tc.constraint_type = 'FOREIGN KEY'
-- ORDER BY tc.table_name, kcu.column_name;

-- ============================================================================
-- END OF SCHEMA
-- ============================================================================

COMMENT ON TABLE users IS 'Parent/user accounts with profile information';
COMMENT ON TABLE children IS 'Children profiles for personalized stories';
COMMENT ON TABLE stories IS 'Generated stories with scenes and media';
COMMENT ON TABLE story_shares IS 'Junction table for story sharing between users';
COMMENT ON TABLE reference_images IS 'User-uploaded reference images for story generation';
COMMENT ON TABLE voice_clones IS 'Cartesia voice clone configurations';
COMMENT ON TABLE iot_devices IS 'ESP32 and IoT device registrations';
COMMENT ON TABLE password_reset_otps IS 'One-time passwords for password reset';
COMMENT ON TABLE user_activities IS 'User activity tracking for analytics';

-- Audit Column Comments
COMMENT ON COLUMN users.created_by IS 'User ID who created this record';
COMMENT ON COLUMN users.updated_by IS 'User ID who last updated this record';

COMMENT ON COLUMN children.created_by IS 'User ID who created this record';
COMMENT ON COLUMN children.updated_by IS 'User ID who last updated this record';

COMMENT ON COLUMN stories.created_by IS 'User ID who created this record';
COMMENT ON COLUMN stories.updated_by IS 'User ID who last updated this record';

COMMENT ON COLUMN voice_clones.created_by IS 'User ID who created this record';
COMMENT ON COLUMN voice_clones.updated_by IS 'User ID who last updated this record';

COMMENT ON COLUMN reference_images.created_by IS 'User ID who created this record';
COMMENT ON COLUMN reference_images.updated_by IS 'User ID who last updated this record';

COMMENT ON COLUMN iot_devices.created_by IS 'User ID who created this record';
COMMENT ON COLUMN iot_devices.updated_by IS 'User ID who last updated this record';

COMMENT ON COLUMN story_shares.created_by IS 'User ID who created this record';
COMMENT ON COLUMN story_shares.updated_by IS 'User ID who last updated this record';

COMMENT ON COLUMN password_reset_otps.created_by IS 'User ID who created this record';
COMMENT ON COLUMN password_reset_otps.updated_by IS 'User ID who last updated this record';

COMMENT ON COLUMN user_activities.created_by IS 'User ID who created this record';
COMMENT ON COLUMN user_activities.updated_by IS 'User ID who last updated this record';

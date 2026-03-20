-- Migration 008: Create user_modules table for capivara module subscriptions
-- This table tracks which capivara modules each user has unlocked.
-- ARA is always unlocked (not stored here — handled in code).

CREATE TABLE IF NOT EXISTS user_modules (
    id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    module_name     TEXT NOT NULL CHECK (module_name IN ('ara', 'ivi', 'oka', 'yara', 'ayvu', 'mbae', 'pora')),
    status          TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'cancelled', 'early_access', 'trial')),
    stripe_subscription_item_id TEXT,  -- Stripe subscription item ID for this module add-on
    unlocked_at     TIMESTAMPTZ DEFAULT NOW(),
    expires_at      TIMESTAMPTZ,       -- NULL = no expiry (active subscription)
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(user_id, module_name)       -- One record per user per module
);

-- Index for fast lookup by user_id (most common query pattern)
CREATE INDEX IF NOT EXISTS idx_user_modules_user_id ON user_modules(user_id);

-- Index for module_name queries (admin analytics)
CREATE INDEX IF NOT EXISTS idx_user_modules_module_name ON user_modules(module_name);

-- Row Level Security
ALTER TABLE user_modules ENABLE ROW LEVEL SECURITY;

-- Users can only read their own module records
CREATE POLICY "Users can view own modules"
    ON user_modules FOR SELECT
    USING (auth.uid() = user_id);

-- Only service role can insert/update (done via Stripe webhook with service key)
CREATE POLICY "Service role can manage modules"
    ON user_modules FOR ALL
    USING (auth.role() = 'service_role');

-- Auto-update updated_at on changes
CREATE OR REPLACE FUNCTION update_user_modules_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_user_modules_updated_at
    BEFORE UPDATE ON user_modules
    FOR EACH ROW EXECUTE FUNCTION update_user_modules_updated_at();

-- Comment for documentation
COMMENT ON TABLE user_modules IS 'Tracks which CAPIVAREX capivara modules each user has unlocked via subscription. ARA is always active and not stored here.';
COMMENT ON COLUMN user_modules.module_name IS 'One of: ara, ivi, oka, yara, ayvu, mbae, pora';
COMMENT ON COLUMN user_modules.status IS 'active=paying, cancelled=churned, early_access=paid but module not launched yet, trial=7-day trial';

-- Migration 003: Create identity_map table for multi-tenancy
-- Replaces the JSON-file-based identity mapping with a Supabase table.

CREATE TABLE IF NOT EXISTS identity_map (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    channel TEXT NOT NULL,              -- 'telegram', 'webapp', etc.
    channel_identifier TEXT NOT NULL,   -- chat_id, session_id, email, etc.
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(channel, channel_identifier)
);

-- Index for fast lookups by channel + identifier
CREATE INDEX IF NOT EXISTS idx_identity_map_channel_identifier
    ON identity_map(channel, channel_identifier);

-- Index for user-based queries
CREATE INDEX IF NOT EXISTS idx_identity_map_user_id
    ON identity_map(user_id);

-- Enable Row Level Security
ALTER TABLE identity_map ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can manage their own identities" ON identity_map
    FOR ALL
    USING (auth.uid() = user_id);

-- Migration 006: Create proactivity_feed table
-- Stores proactive alerts/insights for the webapp feed UI.

CREATE TABLE IF NOT EXISTS proactivity_feed (
    id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id         TEXT NOT NULL,
    type            TEXT NOT NULL DEFAULT 'insight',
    title           TEXT,
    message         TEXT NOT NULL,
    metadata        JSONB DEFAULT '{}',
    is_read         BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT now(),
    read_at         TIMESTAMPTZ
);

-- Fast lookup: unread items per user
CREATE INDEX IF NOT EXISTS idx_proactivity_feed_user_unread
    ON proactivity_feed (user_id, is_read)
    WHERE NOT is_read;

-- Chronological feed per user
CREATE INDEX IF NOT EXISTS idx_proactivity_feed_user_created
    ON proactivity_feed (user_id, created_at DESC);

-- RLS (Row Level Security) — users can only see their own feed
ALTER TABLE proactivity_feed ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own feed"
    ON proactivity_feed FOR SELECT
    USING (auth.uid()::text = user_id);

CREATE POLICY "Users can update own feed"
    ON proactivity_feed FOR UPDATE
    USING (auth.uid()::text = user_id);

-- Service role can insert (proactivity loop writes here)
CREATE POLICY "Service can insert feed items"
    ON proactivity_feed FOR INSERT
    WITH CHECK (true);

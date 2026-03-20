-- Migration 009: Create calendar_events table for proactivity services
-- Used by: commute_optimizer, context_silence, daily_summary,
--          sleep_wake, weekly_planner, weekly_wins
-- Without this table, all proactivity services that use calendar data
-- fail silently and operate without events.

CREATE TABLE IF NOT EXISTS calendar_events (
    id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    title           TEXT NOT NULL,
    description     TEXT,
    start_time      TIMESTAMPTZ NOT NULL,
    end_time        TIMESTAMPTZ,
    location        TEXT,
    source          TEXT DEFAULT 'google',       -- google, microsoft, manual
    source_event_id TEXT,                        -- original event ID from provider
    all_day         BOOLEAN DEFAULT FALSE,
    recurring       BOOLEAN DEFAULT FALSE,
    status          TEXT DEFAULT 'confirmed',    -- confirmed, tentative, cancelled
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(user_id, source, source_event_id)
);

-- Fast lookup by user + time range (most common query pattern)
CREATE INDEX IF NOT EXISTS idx_calendar_events_user_id ON calendar_events(user_id);
CREATE INDEX IF NOT EXISTS idx_calendar_events_user_start ON calendar_events(user_id, start_time);

-- Row Level Security
ALTER TABLE calendar_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own events"
    ON calendar_events FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Service role full access"
    ON calendar_events FOR ALL
    USING (auth.role() = 'service_role');

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION update_calendar_events_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_calendar_events_updated_at
    BEFORE UPDATE ON calendar_events
    FOR EACH ROW EXECUTE FUNCTION update_calendar_events_updated_at();

COMMENT ON TABLE calendar_events IS 'Cached calendar events from Google/Microsoft for proactivity services (daily summary, commute optimizer, weekly planner, sleep/wake, etc.)';

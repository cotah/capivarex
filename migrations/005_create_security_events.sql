-- =============================================================================
-- Migration 005: Create security_events table
-- =============================================================================
-- Purpose : Records authentication failures, rate limit violations,
--           suspicious requests, and other security-relevant events.
-- Sentry  : Fixes PYTHON-Y (PGRST205) and PYTHON-X (HTTPException 500)
--           on GET /api/webapp/security/events
-- Run in  : Supabase Dashboard → SQL Editor (as postgres / service_role)
-- =============================================================================

-- 1. Create the table (idempotent)
CREATE TABLE IF NOT EXISTS public.security_events (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type  TEXT        NOT NULL,
    severity    TEXT        NOT NULL
                            CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    user_id     UUID        REFERENCES public.users(id) ON DELETE SET NULL,
    tenant_id   TEXT,
    ip_address  TEXT,
    endpoint    TEXT,
    details     JSONB       NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. Performance indexes
CREATE INDEX IF NOT EXISTS idx_security_events_user_created
    ON public.security_events (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_security_events_type_severity
    ON public.security_events (event_type, severity, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_security_events_ip_created
    ON public.security_events (ip_address, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_security_events_tenant_created
    ON public.security_events (tenant_id, created_at DESC)
    WHERE tenant_id IS NOT NULL;

-- 3. Row Level Security
ALTER TABLE public.security_events ENABLE ROW LEVEL SECURITY;

-- Drop policies if they already exist (safe re-run)
DROP POLICY IF EXISTS "service_role_full_access"  ON public.security_events;
DROP POLICY IF EXISTS "admin_read_own_tenant"      ON public.security_events;
DROP POLICY IF EXISTS "user_read_own_events"       ON public.security_events;

-- Service role: full access (used by the backend API)
CREATE POLICY "service_role_full_access" ON public.security_events
    FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

-- Authenticated users: read only their own events
CREATE POLICY "user_read_own_events" ON public.security_events
    FOR SELECT
    USING (
        auth.role() = 'authenticated'
        AND user_id = auth.uid()
    );

-- 4. Force PostgREST to reload its schema cache immediately
--    This is required so the table becomes visible to the API
--    without needing a service restart.
NOTIFY pgrst, 'reload schema';

-- =============================================================================
-- Verification query (run after migration to confirm success):
--   SELECT table_name, row_security
--   FROM information_schema.tables
--   WHERE table_schema = 'public' AND table_name = 'security_events';
-- Expected: 1 row with row_security = 'YES'
-- =============================================================================

-- Migration: Create memories and memory_audit_log tables
-- Description: Central auditable memory system replacing JSON file storage
-- Author: Claude AI
-- Date: 2026-02-19

-- Create memories table
CREATE TABLE IF NOT EXISTS memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type TEXT NOT NULL,  -- 'short_term', 'long_term', 'factual'
    content TEXT NOT NULL,
    source TEXT,  -- 'user_input', 'proactivity_insight', etc.
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Index for fast user + type lookups
CREATE INDEX IF NOT EXISTS idx_memories_user_type ON memories(user_id, type);

-- Create memory audit log table
CREATE TABLE IF NOT EXISTS memory_audit_log (
    id BIGSERIAL PRIMARY KEY,
    request_id UUID,
    memory_id UUID REFERENCES memories(id) ON DELETE SET NULL,
    user_id UUID,
    action TEXT NOT NULL,  -- 'created', 'read', 'used_for_prompt'
    timestamp TIMESTAMPTZ DEFAULT now()
);

-- Index for audit log lookups
CREATE INDEX IF NOT EXISTS idx_memory_audit_user ON memory_audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_memory_audit_request ON memory_audit_log(request_id);

-- Enable Row Level Security
ALTER TABLE memories ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_audit_log ENABLE ROW LEVEL SECURITY;

-- RLS Policies: users can only access their own memories
CREATE POLICY "Users can view own memories"
    ON memories FOR SELECT
    USING (user_id = auth.uid());

CREATE POLICY "Users can insert own memories"
    ON memories FOR INSERT
    WITH CHECK (user_id = auth.uid());

CREATE POLICY "Users can delete own memories"
    ON memories FOR DELETE
    USING (user_id = auth.uid());

-- RLS Policies: users can only view their own audit logs
CREATE POLICY "Users can view own audit logs"
    ON memory_audit_log FOR SELECT
    USING (user_id = auth.uid());

-- Service role bypass for backend operations
CREATE POLICY "Service role full access to memories"
    ON memories FOR ALL
    USING (auth.role() = 'service_role');

CREATE POLICY "Service role full access to audit logs"
    ON memory_audit_log FOR ALL
    USING (auth.role() = 'service_role');

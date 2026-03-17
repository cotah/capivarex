-- ============================================================
-- Migration 007: CyberSecurity Bot Tables
-- Run this in Supabase SQL Editor
-- ============================================================

-- 1. cyber_findings — Every scanner finding produces one row
CREATE TABLE IF NOT EXISTS public.cyber_findings (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    scanner         TEXT        NOT NULL,
    finding_type    TEXT        NOT NULL,
    severity        TEXT        NOT NULL CHECK (severity IN ('info', 'low', 'medium', 'high', 'critical')),
    confidence      FLOAT       NOT NULL DEFAULT 0.5,
    status          TEXT        NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'acknowledged', 'in_progress', 'fixed', 'false_positive', 'wont_fix')),
    title           TEXT        NOT NULL,
    description     TEXT,
    file_path       TEXT,
    line_number     INT,
    code_snippet    TEXT,
    suggested_fix   TEXT,
    cve_id          TEXT,
    owasp_category  TEXT,
    evidence        JSONB       NOT NULL DEFAULT '{}',
    metadata        JSONB       NOT NULL DEFAULT '{}',
    autofix_ticket_id TEXT,
    first_seen      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cyber_findings_status     ON public.cyber_findings (status, severity);
CREATE INDEX IF NOT EXISTS idx_cyber_findings_scanner    ON public.cyber_findings (scanner, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cyber_findings_severity   ON public.cyber_findings (severity, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cyber_findings_file       ON public.cyber_findings (file_path);
CREATE INDEX IF NOT EXISTS idx_cyber_findings_fingerprint ON public.cyber_findings (scanner, finding_type, file_path, line_number);

-- RLS
ALTER TABLE public.cyber_findings ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access on cyber_findings"
    ON public.cyber_findings FOR ALL
    USING (auth.role() = 'service_role');

-- 2. cyber_scan_runs — Tracks every scan execution
CREATE TABLE IF NOT EXISTS public.cyber_scan_runs (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    scanner         TEXT        NOT NULL,
    scan_type       TEXT        NOT NULL DEFAULT 'scheduled' CHECK (scan_type IN ('scheduled', 'manual', 'triggered')),
    status          TEXT        NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed', 'cancelled')),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    findings_count  INT         NOT NULL DEFAULT 0,
    new_findings    INT         NOT NULL DEFAULT 0,
    errors          JSONB       NOT NULL DEFAULT '[]',
    duration_ms     INT,
    metadata        JSONB       NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_cyber_scan_runs_scanner ON public.cyber_scan_runs (scanner, started_at DESC);

ALTER TABLE public.cyber_scan_runs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access on cyber_scan_runs"
    ON public.cyber_scan_runs FOR ALL
    USING (auth.role() = 'service_role');

-- 3. cyber_knowledge — RAG knowledge base with pgvector
CREATE TABLE IF NOT EXISTS public.cyber_knowledge (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    category        TEXT        NOT NULL CHECK (category IN ('finding', 'fix', 'pattern', 'advisory', 'false_positive')),
    title           TEXT        NOT NULL,
    content         TEXT        NOT NULL,
    source          TEXT,
    severity        TEXT,
    tags            TEXT[]      DEFAULT '{}',
    embedding       vector(1536),
    metadata        JSONB       NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cyber_knowledge_category ON public.cyber_knowledge (category);

-- pgvector index for semantic search (requires pgvector extension enabled)
CREATE INDEX IF NOT EXISTS idx_cyber_knowledge_embedding
    ON public.cyber_knowledge
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);

ALTER TABLE public.cyber_knowledge ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access on cyber_knowledge"
    ON public.cyber_knowledge FOR ALL
    USING (auth.role() = 'service_role');

-- Semantic search RPC function
CREATE OR REPLACE FUNCTION match_cyber_knowledge(
    query_embedding vector(1536),
    match_threshold float DEFAULT 0.7,
    match_count int DEFAULT 10
)
RETURNS TABLE (
    id uuid,
    category text,
    title text,
    content text,
    severity text,
    tags text[],
    similarity float
)
LANGUAGE plpgsql AS $$
BEGIN
    RETURN QUERY
    SELECT
        ck.id,
        ck.category,
        ck.title,
        ck.content,
        ck.severity,
        ck.tags,
        (1 - (ck.embedding <=> query_embedding))::float AS similarity
    FROM public.cyber_knowledge ck
    WHERE 1 - (ck.embedding <=> query_embedding) > match_threshold
    ORDER BY ck.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- 4. cyber_compliance_scores — Daily compliance snapshot
CREATE TABLE IF NOT EXISTS public.cyber_compliance_scores (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    score_date      DATE        NOT NULL DEFAULT CURRENT_DATE,
    overall_score   FLOAT       NOT NULL,
    category_scores JSONB       NOT NULL DEFAULT '{}',
    open_findings   INT         NOT NULL DEFAULT 0,
    critical_count  INT         NOT NULL DEFAULT 0,
    high_count      INT         NOT NULL DEFAULT 0,
    medium_count    INT         NOT NULL DEFAULT 0,
    low_count       INT         NOT NULL DEFAULT 0,
    metadata        JSONB       NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(score_date)
);

ALTER TABLE public.cyber_compliance_scores ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access on cyber_compliance_scores"
    ON public.cyber_compliance_scores FOR ALL
    USING (auth.role() = 'service_role');

-- ============================================================
-- Notify PostgREST to reload schema cache
-- ============================================================
NOTIFY pgrst, 'reload schema';

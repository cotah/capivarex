-- ==========================================================================
-- Capivarex — Script completo de criação de todas as 25 tabelas
-- ==========================================================================
-- Banco: Supabase (PostgreSQL)
-- Gerado a partir do código do repositório
-- Executar no SQL Editor do Supabase na ordem apresentada
-- ==========================================================================

-- Extensão necessária para gen_random_uuid() / uuid_generate_v4()
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ==========================================================================
-- 1. users  (core)
-- ==========================================================================
CREATE TABLE IF NOT EXISTS users (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email            TEXT UNIQUE NOT NULL,
    full_name        TEXT,
    hashed_password  TEXT NOT NULL,
    plan             TEXT DEFAULT 'basic',
    messages_limit   INTEGER DEFAULT 100,
    messages_used    INTEGER DEFAULT 0,
    use_own_apis     BOOLEAN DEFAULT FALSE,
    telegram_chat_id TEXT,
    location_preference TEXT,
    proactivity_preferences JSONB DEFAULT '{}'::jsonb,
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

-- ==========================================================================
-- 2. conversations  (core)
-- ==========================================================================
CREATE TABLE IF NOT EXISTS conversations (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID REFERENCES users(id) ON DELETE CASCADE,
    title      TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id);

-- ==========================================================================
-- 3. messages  (core)
-- ==========================================================================
CREATE TABLE IF NOT EXISTS messages (
    id              BIGSERIAL PRIMARY KEY,
    conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);

-- ==========================================================================
-- 4. user_vehicles  (Smartcar)
-- ==========================================================================
CREATE TABLE IF NOT EXISTS user_vehicles (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    vehicle_id     VARCHAR(255) NOT NULL UNIQUE,
    access_token   TEXT NOT NULL,
    refresh_token  TEXT NOT NULL,
    expires_at     TIMESTAMPTZ NOT NULL,
    token_type     VARCHAR(50) DEFAULT 'Bearer',
    make           VARCHAR(100),
    model          VARCHAR(100),
    year           INTEGER,
    vin            VARCHAR(17),
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at     TIMESTAMPTZ DEFAULT NOW(),
    last_synced_at TIMESTAMPTZ,
    CONSTRAINT unique_user_vehicle UNIQUE (user_id, vehicle_id)
);

CREATE INDEX IF NOT EXISTS idx_user_vehicles_user_id    ON user_vehicles(user_id);
CREATE INDEX IF NOT EXISTS idx_user_vehicles_vehicle_id ON user_vehicles(vehicle_id);
CREATE INDEX IF NOT EXISTS idx_user_vehicles_expires_at ON user_vehicles(expires_at);

CREATE OR REPLACE FUNCTION update_user_vehicles_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_user_vehicles_updated_at
    BEFORE UPDATE ON user_vehicles
    FOR EACH ROW
    EXECUTE FUNCTION update_user_vehicles_updated_at();

ALTER TABLE user_vehicles ENABLE ROW LEVEL SECURITY;

CREATE POLICY user_vehicles_select_policy ON user_vehicles
    FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY user_vehicles_insert_policy ON user_vehicles
    FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY user_vehicles_update_policy ON user_vehicles
    FOR UPDATE USING (auth.uid() = user_id);
CREATE POLICY user_vehicles_delete_policy ON user_vehicles
    FOR DELETE USING (auth.uid() = user_id);

GRANT SELECT, INSERT, UPDATE, DELETE ON user_vehicles TO authenticated;

-- ==========================================================================
-- 5. memories  (bot memory)
-- ==========================================================================
CREATE TABLE IF NOT EXISTS memories (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type       TEXT NOT NULL,       -- 'short_term', 'long_term', 'factual'
    content    TEXT NOT NULL,
    source     TEXT,                -- 'user_input', 'proactivity_insight', etc.
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_memories_user_type ON memories(user_id, type);

ALTER TABLE memories ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own memories"
    ON memories FOR SELECT USING (user_id = auth.uid());
CREATE POLICY "Users can insert own memories"
    ON memories FOR INSERT WITH CHECK (user_id = auth.uid());
CREATE POLICY "Users can delete own memories"
    ON memories FOR DELETE USING (user_id = auth.uid());
CREATE POLICY "Service role full access to memories"
    ON memories FOR ALL USING (auth.role() = 'service_role');

-- ==========================================================================
-- 6. memory_audit_log
-- ==========================================================================
CREATE TABLE IF NOT EXISTS memory_audit_log (
    id         BIGSERIAL PRIMARY KEY,
    request_id UUID,
    memory_id  UUID REFERENCES memories(id) ON DELETE SET NULL,
    user_id    UUID,
    action     TEXT NOT NULL,       -- 'created', 'read', 'used_for_prompt'
    timestamp  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_memory_audit_user    ON memory_audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_memory_audit_request ON memory_audit_log(request_id);

ALTER TABLE memory_audit_log ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own audit logs"
    ON memory_audit_log FOR SELECT USING (user_id = auth.uid());
CREATE POLICY "Service role full access to audit logs"
    ON memory_audit_log FOR ALL USING (auth.role() = 'service_role');

-- ==========================================================================
-- 7. identity_map  (multi-tenancy)
-- ==========================================================================
CREATE TABLE IF NOT EXISTS identity_map (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id            UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    channel            TEXT NOT NULL,           -- 'telegram', 'webapp', etc.
    channel_identifier TEXT NOT NULL,           -- chat_id, session_id, email
    created_at         TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(channel, channel_identifier)
);

CREATE INDEX IF NOT EXISTS idx_identity_map_channel_identifier
    ON identity_map(channel, channel_identifier);
CREATE INDEX IF NOT EXISTS idx_identity_map_user_id
    ON identity_map(user_id);

ALTER TABLE identity_map ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can manage their own identities" ON identity_map
    FOR ALL USING (auth.uid() = user_id);

-- ==========================================================================
-- 8. notes  (notas pessoais)
-- ==========================================================================
CREATE TABLE IF NOT EXISTS notes (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    TEXT NOT NULL,
    chat_id    TEXT NOT NULL,
    title      TEXT NOT NULL,
    content    TEXT NOT NULL,
    tags       TEXT[] DEFAULT '{}',
    pinned     BOOLEAN DEFAULT FALSE,
    archived   BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS notes_user_idx ON notes(user_id);

-- ==========================================================================
-- 9. reminders  (lembretes)
-- ==========================================================================
CREATE TABLE IF NOT EXISTS reminders (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    TEXT NOT NULL,
    chat_id    TEXT NOT NULL,
    message    TEXT NOT NULL,
    remind_at  TIMESTAMPTZ NOT NULL,
    recurrence TEXT,                -- NULL, 'daily', 'weekly', 'monthly'
    fired      BOOLEAN DEFAULT FALSE,
    cancelled  BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reminders_user    ON reminders(user_id);
CREATE INDEX IF NOT EXISTS idx_reminders_due     ON reminders(remind_at)
    WHERE fired = FALSE AND cancelled = FALSE;

-- ==========================================================================
-- 10. proactivity_preferences
-- ==========================================================================
CREATE TABLE IF NOT EXISTS proactivity_preferences (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE UNIQUE,
    enabled                BOOLEAN DEFAULT FALSE,
    check_interval_minutes INTEGER DEFAULT 30,
    insights_enabled       BOOLEAN DEFAULT TRUE,
    created_at             TIMESTAMPTZ DEFAULT NOW(),
    updated_at             TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_proactivity_pref_user ON proactivity_preferences(user_id);

-- ==========================================================================
-- 11. user_context
-- ==========================================================================
CREATE TABLE IF NOT EXISTS user_context (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    context_type TEXT NOT NULL,
    data         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, context_type)
);

CREATE INDEX IF NOT EXISTS idx_user_context_user_type
    ON user_context(user_id, context_type);

-- ==========================================================================
-- 12. car_connections  (Smartcar OAuth tokens)
-- ==========================================================================
CREATE TABLE IF NOT EXISTS car_connections (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    vehicle_id    TEXT NOT NULL,
    access_token  TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    expires_at    TIMESTAMPTZ NOT NULL,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, vehicle_id)
);

CREATE INDEX IF NOT EXISTS idx_car_connections_user ON car_connections(user_id);

-- ==========================================================================
-- 13. smartthings_connections  (SmartThings OAuth)
-- ==========================================================================
CREATE TABLE IF NOT EXISTS smartthings_connections (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE UNIQUE,
    access_token     TEXT NOT NULL,
    refresh_token    TEXT NOT NULL,
    expires_at       TIMESTAMPTZ NOT NULL,
    installed_app_id TEXT,
    location_id      TEXT,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_smartthings_conn_user ON smartthings_connections(user_id);

-- ==========================================================================
-- 14. calendar_connections  (Google Calendar OAuth)
-- ==========================================================================
CREATE TABLE IF NOT EXISTS calendar_connections (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE UNIQUE,
    credentials TEXT NOT NULL,       -- JSON criptografado
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_calendar_conn_user ON calendar_connections(user_id);

-- ==========================================================================
-- 15. github_connections
-- ==========================================================================
CREATE TABLE IF NOT EXISTS github_connections (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE UNIQUE,
    github_username TEXT NOT NULL,
    access_token    TEXT NOT NULL,       -- criptografado
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_github_conn_user ON github_connections(user_id);

-- ==========================================================================
-- 16. smartthings_tokens  (usados na rota SmartThings OAuth)
-- ==========================================================================
CREATE TABLE IF NOT EXISTS smartthings_tokens (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE UNIQUE,
    access_token  TEXT NOT NULL,       -- criptografado
    refresh_token TEXT NOT NULL,       -- criptografado
    expires_at    TIMESTAMPTZ NOT NULL,
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_smartthings_tokens_user ON smartthings_tokens(user_id);

-- ==========================================================================
-- 17. smartthings_devices
-- ==========================================================================
CREATE TABLE IF NOT EXISTS smartthings_devices (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    device_id    TEXT NOT NULL,
    label        TEXT,
    device_type  TEXT DEFAULT 'unknown',
    room         TEXT,
    capabilities TEXT[],
    updated_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, device_id)
);

CREATE INDEX IF NOT EXISTS idx_smartthings_devices_user ON smartthings_devices(user_id);

-- ==========================================================================
-- 18. email_inbox  (agente de e-mail)
-- ==========================================================================
CREATE TABLE IF NOT EXISTS email_inbox (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account     TEXT,
    email_id    TEXT,
    thread_id   TEXT,
    message_id  TEXT,
    from_email  TEXT,
    from_name   TEXT,
    to_email    TEXT,
    subject     TEXT,
    body_text   TEXT,
    received_at TIMESTAMPTZ,
    read        BOOLEAN DEFAULT FALSE,
    replied     BOOLEAN DEFAULT FALSE,
    urgency     TEXT DEFAULT 'medium',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, email_id)
);

CREATE INDEX IF NOT EXISTS idx_email_inbox_user ON email_inbox(user_id);
CREATE INDEX IF NOT EXISTS idx_email_inbox_received ON email_inbox(received_at DESC);

-- ==========================================================================
-- 19. twilio_calls  (histórico de chamadas)
-- ==========================================================================
CREATE TABLE IF NOT EXISTS twilio_calls (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    call_sid            TEXT NOT NULL UNIQUE,
    tenant_id           TEXT NOT NULL,
    from_number         TEXT NOT NULL,
    to_number           TEXT NOT NULL,
    destination_country TEXT,
    status              TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_twilio_calls_tenant ON twilio_calls(tenant_id);
CREATE INDEX IF NOT EXISTS idx_twilio_calls_created ON twilio_calls(created_at DESC);

-- ==========================================================================
-- 20. tenant_subscriptions  (planos/assinaturas)
-- ==========================================================================
CREATE TABLE IF NOT EXISTS tenant_subscriptions (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id  TEXT NOT NULL,
    plan       TEXT NOT NULL DEFAULT 'free',
    active     BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tenant_subs_tenant ON tenant_subscriptions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_tenant_subs_active ON tenant_subscriptions(tenant_id)
    WHERE active = TRUE;

-- ==========================================================================
-- 21. tenant_usage  (consumo de cotas)
-- ==========================================================================
CREATE TABLE IF NOT EXISTS tenant_usage (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    TEXT NOT NULL,
    resource     TEXT NOT NULL,
    used         INTEGER NOT NULL DEFAULT 0,
    period_start TEXT NOT NULL,       -- ISO date ou 'stock'
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tenant_id, resource, period_start)
);

CREATE INDEX IF NOT EXISTS idx_tenant_usage_lookup
    ON tenant_usage(tenant_id, resource, period_start);

-- ==========================================================================
-- 22. tenant_usage_log  (log detalhado de consumo)
-- ==========================================================================
CREATE TABLE IF NOT EXISTS tenant_usage_log (
    id         BIGSERIAL PRIMARY KEY,
    tenant_id  TEXT NOT NULL,
    resource   TEXT NOT NULL,
    amount     INTEGER NOT NULL DEFAULT 1,
    plan       TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tenant_usage_log_tenant ON tenant_usage_log(tenant_id);

-- ==========================================================================
-- 23. mercado_compras  (compras de supermercado)
-- ==========================================================================
CREATE TABLE IF NOT EXISTS mercado_compras (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id         TEXT NOT NULL,
    mercado         TEXT NOT NULL,
    data_compra     DATE NOT NULL,
    total           NUMERIC(10,2) DEFAULT 0,
    fonte_extracao  TEXT,            -- 'gpt4_vision', 'google_vision'
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mercado_compras_chat  ON mercado_compras(chat_id);
CREATE INDEX IF NOT EXISTS idx_mercado_compras_data  ON mercado_compras(data_compra);

-- ==========================================================================
-- 24. mercado_itens  (itens das compras)
-- ==========================================================================
CREATE TABLE IF NOT EXISTS mercado_itens (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    compra_id       UUID REFERENCES mercado_compras(id) ON DELETE CASCADE,
    chat_id         TEXT NOT NULL,
    produto         TEXT NOT NULL,
    categoria       TEXT,
    quantidade      NUMERIC(10,3) DEFAULT 1,
    unidade         TEXT DEFAULT 'un',
    preco_total     NUMERIC(10,2) DEFAULT 0,
    preco_unitario  NUMERIC(10,4) DEFAULT 0,
    mercado         TEXT,
    data_compra     DATE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mercado_itens_compra  ON mercado_itens(compra_id);
CREATE INDEX IF NOT EXISTS idx_mercado_itens_chat    ON mercado_itens(chat_id);
CREATE INDEX IF NOT EXISTS idx_mercado_itens_produto ON mercado_itens(produto);

-- ==========================================================================
-- 25. projects  (workspace)
-- ==========================================================================
CREATE TABLE IF NOT EXISTS projects (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    description TEXT DEFAULT '',
    language    TEXT DEFAULT '',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, name)
);

CREATE INDEX IF NOT EXISTS idx_projects_user ON projects(user_id);

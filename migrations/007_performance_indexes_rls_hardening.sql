-- Migration 007: Performance indexes + RLS hardening + trigger cleanup
-- Author: Audit Report
-- Date: 2026-03-18
-- Description:
--   1. Add missing composite index on webapp_messages (conversation_id, created_at)
--   2. Add missing index on users.stripe_customer_id for webhook lookups
--   3. Remove duplicate trigger on conversations table
--   4. Harden RLS policies to require authenticated role

-- ============================================================================
-- 1. PERFORMANCE INDEXES
-- ============================================================================

-- webapp_messages: composite index for ORDER BY created_at queries per conversation
-- Fixes: Seq Scan on webapp.py line 771 — ORDER("created_at") without index
CREATE INDEX IF NOT EXISTS idx_webapp_messages_conv_created
    ON webapp_messages (conversation_id, created_at);

-- users: index for Stripe webhook customer lookups
-- Fixes: O(N) scan when Stripe webhook looks up user by stripe_customer_id
CREATE INDEX IF NOT EXISTS idx_users_stripe_customer_id
    ON users (stripe_customer_id)
    WHERE stripe_customer_id IS NOT NULL;

-- ============================================================================
-- 2. REMOVE DUPLICATE TRIGGER on conversations
-- ============================================================================
-- Two triggers do the same thing: update updated_at on UPDATE
-- Keep the one with the standard naming convention

DROP TRIGGER IF EXISTS update_conversations_updated_at ON conversations;
-- Keeps: trigger_update_conversation_updated_at (original)

-- ============================================================================
-- 3. HARDEN RLS POLICIES — require authenticated role
-- ============================================================================
-- Current policies trust JWT 'sub' claim without checking role.
-- An anon token with a forged 'sub' could bypass RLS.
-- Fix: Add auth.role() = 'authenticated' check.

-- webapp_conversations: drop and recreate with role check
DO $$
BEGIN
    -- Only alter if the table exists (safe for fresh installs)
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'webapp_conversations') THEN
        -- Drop existing permissive policies
        DROP POLICY IF EXISTS "Users can view own conversations" ON webapp_conversations;
        DROP POLICY IF EXISTS "Users can insert own conversations" ON webapp_conversations;
        DROP POLICY IF EXISTS "Users can update own conversations" ON webapp_conversations;
        DROP POLICY IF EXISTS "Users can delete own conversations" ON webapp_conversations;

        -- Recreate with role check
        CREATE POLICY "Users can view own conversations"
            ON webapp_conversations FOR SELECT
            USING (auth.role() = 'authenticated' AND user_id = auth.uid()::text);

        CREATE POLICY "Users can insert own conversations"
            ON webapp_conversations FOR INSERT
            WITH CHECK (auth.role() = 'authenticated' AND user_id = auth.uid()::text);

        CREATE POLICY "Users can update own conversations"
            ON webapp_conversations FOR UPDATE
            USING (auth.role() = 'authenticated' AND user_id = auth.uid()::text);

        CREATE POLICY "Users can delete own conversations"
            ON webapp_conversations FOR DELETE
            USING (auth.role() = 'authenticated' AND user_id = auth.uid()::text);
    END IF;
END $$;

-- webapp_messages: drop and recreate with role check
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'webapp_messages') THEN
        DROP POLICY IF EXISTS "Users can view own messages" ON webapp_messages;
        DROP POLICY IF EXISTS "Users can insert own messages" ON webapp_messages;
        DROP POLICY IF EXISTS "Users can update own messages" ON webapp_messages;
        DROP POLICY IF EXISTS "Users can delete own messages" ON webapp_messages;

        CREATE POLICY "Users can view own messages"
            ON webapp_messages FOR SELECT
            USING (
                auth.role() = 'authenticated'
                AND conversation_id IN (
                    SELECT id FROM webapp_conversations WHERE user_id = auth.uid()::text
                )
            );

        CREATE POLICY "Users can insert own messages"
            ON webapp_messages FOR INSERT
            WITH CHECK (
                auth.role() = 'authenticated'
                AND conversation_id IN (
                    SELECT id FROM webapp_conversations WHERE user_id = auth.uid()::text
                )
            );
    END IF;
END $$;

-- ============================================================================
-- NOTES:
-- - Service role bypasses RLS, so backend operations are unaffected.
-- - These policies only affect direct Supabase client access (frontend/anon).
-- - Run this migration via Supabase SQL Editor or supabase db push.
-- ============================================================================

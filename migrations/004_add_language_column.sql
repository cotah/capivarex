-- i18n Phase 2: Add language preference column
-- Run in Supabase SQL Editor

ALTER TABLE user_preferences
ADD COLUMN IF NOT EXISTS language TEXT DEFAULT 'en';

COMMENT ON COLUMN user_preferences.language IS 'User preferred language: en, pt, es';

-- Verify
SELECT column_name, data_type, column_default
FROM information_schema.columns
WHERE table_name = 'user_preferences' AND column_name = 'language';

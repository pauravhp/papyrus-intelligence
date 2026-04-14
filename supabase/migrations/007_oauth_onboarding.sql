-- 007_oauth_onboarding.sql
--
-- Replaces BYOK credential columns with Todoist OAuth token storage.
-- Existing pgcrypto functions were already dropped in migration 006.
-- Run against local Supabase before applying to production.

-- Add Todoist OAuth token column
ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS todoist_oauth_token jsonb;
-- Stores: {"access_token": "...", "granted_at": "<ISO-8601>"}
-- Todoist access tokens are indefinite — no refresh_token or expiry.

-- Drop obsolete BYOK credential columns
ALTER TABLE public.users
    DROP COLUMN IF EXISTS todoist_api_key,
    DROP COLUMN IF EXISTS groq_api_key,
    DROP COLUMN IF EXISTS anthropic_api_key;

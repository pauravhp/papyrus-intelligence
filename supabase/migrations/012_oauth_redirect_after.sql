-- supabase/migrations/012_oauth_redirect_after.sql
--
-- Adds a temporary storage column for the OAuth post-callback redirect URL.
-- Written at OAuth flow start (google_auth/todoist_auth), read + cleared in callback.
-- Allows reconnecting from Settings to return to /dashboard/settings instead of /onboard.

ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS oauth_redirect_after text;

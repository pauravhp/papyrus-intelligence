-- 010_google_idp.sql
-- Update handle_new_user to read 'full_name' (Google OAuth) with
-- fallback to 'name' (legacy email/password signups).
-- CREATE OR REPLACE updates the function in-place; the trigger
-- binding on_auth_user_created stays attached automatically.
--
-- Note: no backfill needed — all existing accounts are dev test accounts;
-- no real Google OAuth users exist prior to this migration.
--
-- Note: Google OAuth does not supply 'timezone'; it remains NULL and is
-- set explicitly during the onboarding flow.

CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER AS
$$
BEGIN
    INSERT INTO public.users (id, name, timezone)
    VALUES (
        NEW.id,
        COALESCE(
            NEW.raw_user_meta_data ->> 'full_name',
            NEW.raw_user_meta_data ->> 'name'
        ),
        NEW.raw_user_meta_data ->> 'timezone'
    )
    ON CONFLICT (id) DO NOTHING;
    RETURN NEW;
END;
$$;

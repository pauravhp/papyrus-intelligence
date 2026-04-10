-- =============================================================================
-- 001_initial.sql
-- Multi-user schema for schedule-for-me.
--
-- Apply via Supabase dashboard (SQL editor) or:
--   supabase db push  (after `supabase link --project-ref <ref>`)
--
-- Requires: pgcrypto extension (enabled by default on Supabase).
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Extensions
-- ---------------------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS pgcrypto;


-- ---------------------------------------------------------------------------
-- users
--
-- Extends Supabase auth.users. One row per registered user.
-- Sensitive credential fields are encrypted at rest using pgcrypto's
-- symmetric AES encryption. The encryption key must be stored as a Supabase
-- Vault secret (see README below) — never hardcoded here.
--
-- config (jsonb): the full contents of context.json for this user.
--   Structure is defined by context.template.json. The onboarding flow
--   populates this column once --onboard Stage 3 completes.
-- ---------------------------------------------------------------------------

CREATE TABLE public.users (
    id                  uuid        PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    name                text,
    timezone            text,
    todoist_api_key     text,       -- encrypted; use encrypt_api_key() / decrypt_api_key()
    groq_api_key        text,       -- encrypted
    google_credentials  jsonb,      -- encrypted as jsonb→text→pgp_sym_encrypt→text
    config              jsonb       NOT NULL DEFAULT '{}'::jsonb,
    created_at          timestamptz NOT NULL DEFAULT now()
);

-- Convenience functions for encrypting / decrypting API key fields.
-- Pass current_setting('app.encryption_key') as the passphrase — this is set
-- per-session by the FastAPI backend from the Supabase Vault secret.

-- Note: on Supabase, pgcrypto is installed in the `extensions` schema.
-- The functions must be called with the schema prefix.

CREATE OR REPLACE FUNCTION encrypt_field(plaintext text) RETURNS text
    LANGUAGE sql SECURITY DEFINER AS
$$
    SELECT encode(
        extensions.pgp_sym_encrypt(plaintext, current_setting('app.encryption_key')),
        'base64'
    );
$$;

CREATE OR REPLACE FUNCTION decrypt_field(ciphertext text) RETURNS text
    LANGUAGE sql SECURITY DEFINER AS
$$
    SELECT extensions.pgp_sym_decrypt(
        decode(ciphertext, 'base64'),
        current_setting('app.encryption_key')
    );
$$;


-- ---------------------------------------------------------------------------
-- task_history
--
-- Mirrors the SQLite task_history table exactly.
-- SQLite types mapped: INTEGER → bigint, TEXT → text, REAL → numeric.
-- task_id is unique per user (a Todoist task_id is globally unique already,
-- but we scope the unique constraint to (user_id, task_id) for safety).
-- ---------------------------------------------------------------------------

CREATE TABLE public.task_history (
    id                      bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id                 uuid        NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    task_id                 text        NOT NULL,
    task_name               text,
    project_id              text,
    estimated_duration_mins bigint,
    actual_duration_mins    bigint,
    scheduled_at            text,
    completed_at            text,
    day_of_week             text,
    was_rescheduled         bigint      DEFAULT 0,
    reschedule_count        bigint      DEFAULT 0,
    was_late_night_prior    bigint      DEFAULT 0,
    cognitive_load_label    text,
    created_at              text        DEFAULT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'),

    -- Phase-3 habit-learning columns
    time_of_day_bucket      text,
    window_type             text,
    was_deep_work           bigint,
    session_number_today    bigint,
    back_to_back            bigint,
    pre_meeting             bigint,
    estimated_vs_actual_ratio numeric,
    incomplete_reason       text,
    sync_source             text,
    was_agent_scheduled     bigint,
    mood_tag                text,

    CONSTRAINT task_history_user_task_unique UNIQUE (user_id, task_id)
);


-- ---------------------------------------------------------------------------
-- schedule_log
--
-- Mirrors the SQLite schedule_log table exactly.
-- ---------------------------------------------------------------------------

CREATE TABLE public.schedule_log (
    id              bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id         uuid        NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    run_at          text        NOT NULL,
    schedule_date   text        NOT NULL,
    proposed_json   text,
    confirmed       bigint      DEFAULT 0,
    confirmed_at    text,
    diff_json       text,
    replan_trigger  text,
    quality_score   numeric
);


-- ---------------------------------------------------------------------------
-- project_budgets
--
-- Mirrors the SQLite project_budgets table exactly.
-- ---------------------------------------------------------------------------

CREATE TABLE public.project_budgets (
    id                  bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id             uuid        NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    todoist_task_id     text        NOT NULL,
    project_name        text        NOT NULL,
    total_budget_hours  numeric     NOT NULL,
    remaining_hours     numeric     NOT NULL,
    session_min_minutes bigint      NOT NULL DEFAULT 60,
    session_max_minutes bigint      NOT NULL DEFAULT 180,
    deadline            text,
    priority            bigint      NOT NULL DEFAULT 3,
    created_at          text        NOT NULL,
    updated_at          text        NOT NULL,

    CONSTRAINT project_budgets_user_task_unique UNIQUE (user_id, todoist_task_id)
);


-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------

CREATE INDEX idx_task_history_user_id
    ON public.task_history(user_id);

CREATE INDEX idx_schedule_log_user_id
    ON public.schedule_log(user_id);

CREATE INDEX idx_schedule_log_user_date
    ON public.schedule_log(user_id, schedule_date);

CREATE INDEX idx_project_budgets_user_id
    ON public.project_budgets(user_id);


-- ---------------------------------------------------------------------------
-- Row-Level Security
-- ---------------------------------------------------------------------------

ALTER TABLE public.users          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.task_history   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.schedule_log   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.project_budgets ENABLE ROW LEVEL SECURITY;

-- users: each user sees and modifies only their own row
CREATE POLICY users_self ON public.users
    USING      (id = auth.uid())
    WITH CHECK (id = auth.uid());

-- task_history
CREATE POLICY task_history_self ON public.task_history
    USING      (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

-- schedule_log
CREATE POLICY schedule_log_self ON public.schedule_log
    USING      (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

-- project_budgets
CREATE POLICY project_budgets_self ON public.project_budgets
    USING      (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());


-- ---------------------------------------------------------------------------
-- Auto-create users row on Supabase auth signup
--
-- Triggered by auth.users INSERT. Pulls name + timezone from the raw_user_meta_data
-- JSON that the client can pass during signUp({ data: { name, timezone } }).
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER AS
$$
BEGIN
    INSERT INTO public.users (id, name, timezone)
    VALUES (
        NEW.id,
        NEW.raw_user_meta_data ->> 'name',
        NEW.raw_user_meta_data ->> 'timezone'
    )
    ON CONFLICT (id) DO NOTHING;
    RETURN NEW;
END;
$$;

CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

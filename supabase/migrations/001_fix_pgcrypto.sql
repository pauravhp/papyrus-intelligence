-- =============================================================================
-- 001_fix_pgcrypto.sql
--
-- Run this manually in the Supabase SQL editor to complete the 001_initial
-- migration that failed at the encrypt_field / decrypt_field functions.
--
-- The original migration created the users table successfully but stopped
-- before creating these functions. This file picks up from that point.
-- =============================================================================

-- Fix: pgcrypto lives in the extensions schema on Supabase
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

-- task_history
CREATE TABLE IF NOT EXISTS public.task_history (
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

-- schedule_log
CREATE TABLE IF NOT EXISTS public.schedule_log (
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

-- project_budgets
CREATE TABLE IF NOT EXISTS public.project_budgets (
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

-- Indexes
CREATE INDEX IF NOT EXISTS idx_task_history_user_id    ON public.task_history(user_id);
CREATE INDEX IF NOT EXISTS idx_schedule_log_user_id    ON public.schedule_log(user_id);
CREATE INDEX IF NOT EXISTS idx_schedule_log_user_date  ON public.schedule_log(user_id, schedule_date);
CREATE INDEX IF NOT EXISTS idx_project_budgets_user_id ON public.project_budgets(user_id);

-- RLS
ALTER TABLE public.users           ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.task_history    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.schedule_log    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.project_budgets ENABLE ROW LEVEL SECURITY;

CREATE POLICY users_self ON public.users
    USING (id = auth.uid()) WITH CHECK (id = auth.uid());

CREATE POLICY task_history_self ON public.task_history
    USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

CREATE POLICY schedule_log_self ON public.schedule_log
    USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

CREATE POLICY project_budgets_self ON public.project_budgets
    USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

-- Auth trigger
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

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

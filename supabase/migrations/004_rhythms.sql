-- Replaces project_budgets with a leaner rhythms model.
-- project_budgets.todoist_task_id NOT NULL was fixed in 003;
-- that migration is superseded here — drop the table entirely.

DROP TABLE IF EXISTS public.project_budgets;

CREATE TABLE public.rhythms (
    id                  bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id             uuid        NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    rhythm_name         text        NOT NULL,
    sessions_per_week   int         NOT NULL DEFAULT 1,
    session_min_minutes int         NOT NULL DEFAULT 60,
    session_max_minutes int         NOT NULL DEFAULT 120,
    end_date            date,                           -- NULL = ongoing; soft end, not enforced hard
    sort_order          int         NOT NULL DEFAULT 0, -- lower = scheduled first
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_rhythms_user_id ON public.rhythms(user_id);

ALTER TABLE public.rhythms ENABLE ROW LEVEL SECURITY;

CREATE POLICY rhythms_self ON public.rhythms
    USING      (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

-- nudge_dismissals
--
-- Tracks per-instance and per-type nudge dismissals.
-- instance_key = task_id / rhythm_id for per-instance dismiss.
-- instance_key = '__type__' for per-type dismiss (sentinel avoids NULL UNIQUE issues).
-- ---------------------------------------------------------------------------

CREATE TABLE public.nudge_dismissals (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id      uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    nudge_type   text NOT NULL,
    instance_key text NOT NULL DEFAULT '__type__',
    dismissed_at timestamptz NOT NULL DEFAULT now(),
    mode         text NOT NULL DEFAULT 'forever',
    UNIQUE(user_id, nudge_type, instance_key)
);

CREATE INDEX idx_nudge_dismissals_user ON public.nudge_dismissals(user_id, nudge_type);

ALTER TABLE public.nudge_dismissals ENABLE ROW LEVEL SECURITY;

CREATE POLICY nudge_dismissals_self ON public.nudge_dismissals
    USING      (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

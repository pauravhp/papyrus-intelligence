-- Repair a user row whose users.config.sleep has null fields, which crashes
-- compute_free_windows in src/scheduler.py (NoneType.strip()).
--
-- The bug: dict.get(key, default) returns None when the key exists with a
-- null value — only the missing-key case falls back to the default. So a
-- stored sleep dict with explicit nulls bypasses the in-code defaults and
-- the planner 500s.
--
-- A permanent fix lives in api/services/defaults.with_sleep_defaults() and
-- in src/scheduler.py's read sites. This script is the one-off rescue for
-- rows that already landed in the bad state (e.g. user 8222c77d-…).
--
-- HOW TO USE
-- 1. Open Supabase SQL Editor (project: papyrus).
-- 2. Run the SELECT block first and confirm the user's current sleep dict
--    has nulls or missing keys.
-- 3. Run the UPDATE block. It uses jsonb_strip_nulls + concatenation, so
--    any non-null values the user already set are preserved.

-- ── 1. Inspect current state ──────────────────────────────────────────────
SELECT
  id,
  config -> 'sleep' AS current_sleep
FROM users
WHERE id = '8222c77d-9c0c-470c-a318-6d33feb6ef62';

-- ── 2. Apply defaults, preserving any non-null fields the user already set ─
-- jsonb_strip_nulls drops null-valued keys; the right-hand-side defaults
-- supply them; '||' favours the left operand for any key present in both,
-- so non-null user values win.
UPDATE users
SET config = jsonb_set(
  config,
  '{sleep}',
  jsonb_strip_nulls(COALESCE(config -> 'sleep', '{}'::jsonb))
  || jsonb_build_object(
       'default_wake_time',       COALESCE(NULLIF(config #>> '{sleep,default_wake_time}',       ''), '09:00'),
       'morning_buffer_minutes',  COALESCE((config #>> '{sleep,morning_buffer_minutes}')::int,    90),
       'first_task_not_before',   COALESCE(NULLIF(config #>> '{sleep,first_task_not_before}',   ''), '10:30'),
       'no_tasks_after',          COALESCE(NULLIF(config #>> '{sleep,no_tasks_after}',          ''), '23:00'),
       'weekend_nothing_before',  COALESCE(NULLIF(config #>> '{sleep,weekend_nothing_before}',  ''), '13:00'),
       'weekend_days',            COALESCE(config #> '{sleep,weekend_days}', '["saturday","sunday"]'::jsonb)
     )
)
WHERE id = '8222c77d-9c0c-470c-a318-6d33feb6ef62';

-- ── 3. Verify ─────────────────────────────────────────────────────────────
SELECT
  id,
  config -> 'sleep' AS new_sleep
FROM users
WHERE id = '8222c77d-9c0c-470c-a318-6d33feb6ef62';

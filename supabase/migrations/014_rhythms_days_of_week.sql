-- Add an optional days_of_week column to rhythms so users can pin a rhythm
-- to specific weekdays (e.g. "Mon/Wed/Fri only"). NULL means "no restriction"
-- — the scheduler is free to place the rhythm on any day, as before.
--
-- Stored as a text[] of lowercase ISO weekday names to match the existing
-- convention in users.config.sleep.weekend_days. Backfill leaves existing
-- rhythms NULL to preserve current scheduler behaviour.

ALTER TABLE public.rhythms
    ADD COLUMN IF NOT EXISTS days_of_week text[];

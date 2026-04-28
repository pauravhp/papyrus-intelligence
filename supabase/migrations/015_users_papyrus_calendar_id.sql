-- Cache the GCal calendar id of the auto-created "Papyrus" calendar so
-- subsequent /api/import/commit calls don't re-list-or-create it on every
-- run. Populated lazily on first migration-assistant commit per user.
--
-- Nullable: existing users have no Papyrus calendar yet. The migration
-- assistant route is the only writer; cleared by hand if the user revokes
-- the calendar.app.created scope.

ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS papyrus_calendar_id text;

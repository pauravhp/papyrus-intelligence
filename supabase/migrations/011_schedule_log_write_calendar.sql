-- supabase/migrations/011_schedule_log_write_calendar.sql
-- Stores which GCal calendar each confirmed schedule was written to.
-- Used by replan to delete events from the correct calendar even if the user
-- later changes their write_calendar_id config.
ALTER TABLE public.schedule_log
ADD COLUMN IF NOT EXISTS gcal_write_calendar_id TEXT DEFAULT 'primary';

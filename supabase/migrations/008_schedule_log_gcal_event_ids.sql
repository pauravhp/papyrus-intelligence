ALTER TABLE public.schedule_log
ADD COLUMN IF NOT EXISTS gcal_event_ids TEXT DEFAULT '[]';

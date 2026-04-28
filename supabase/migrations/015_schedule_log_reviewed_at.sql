-- supabase/migrations/015_schedule_log_reviewed_at.sql

ALTER TABLE schedule_log
  ADD COLUMN IF NOT EXISTS reviewed_at timestamptz;

CREATE INDEX IF NOT EXISTS idx_schedule_log_user_unreviewed
  ON schedule_log(user_id, schedule_date)
  WHERE confirmed = 1 AND reviewed_at IS NULL;

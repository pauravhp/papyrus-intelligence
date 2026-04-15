-- supabase/migrations/009_task_review_data_model.sql

-- 1. Incomplete reason enum
CREATE TYPE incomplete_reason_enum AS ENUM (
  'ran_out_of_time',
  'deprioritized',
  'blocked',
  'scope_grew',
  'low_energy',
  'forgot'
);

-- 2. Rhythm completions table
CREATE TABLE rhythm_completions (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id       uuid REFERENCES users(id) ON DELETE CASCADE,
  rhythm_id     bigint REFERENCES rhythms(id) ON DELETE CASCADE,
  completed_on  date NOT NULL,
  created_at    timestamptz DEFAULT now(),
  UNIQUE (user_id, rhythm_id, completed_on)
);

-- 3. Add schedule_date to task_history for recurring task support
ALTER TABLE task_history ADD COLUMN IF NOT EXISTS schedule_date date;

-- 4. Drop old unique constraint and replace with one that includes schedule_date
ALTER TABLE task_history DROP CONSTRAINT IF EXISTS task_history_user_task_unique;
ALTER TABLE task_history ADD CONSTRAINT task_history_user_task_date_unique
  UNIQUE (user_id, task_id, schedule_date);

-- 5. Migrate incomplete_reason column to enum type
-- (nulls pass through; any invalid text values will error — check for dirty data first)
ALTER TABLE task_history
  ALTER COLUMN incomplete_reason TYPE incomplete_reason_enum
  USING incomplete_reason::incomplete_reason_enum;

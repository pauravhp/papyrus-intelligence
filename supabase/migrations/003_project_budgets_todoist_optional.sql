-- project_budgets.todoist_task_id was carried over from the SQLite schema but is
-- unused in the Supabase API path (project_service.py). The NOT NULL constraint
-- and the unique index on it block every create_project insert.
-- Make it nullable and drop the constraint so projects can be created from the
-- agent without a Todoist backing task.

ALTER TABLE public.project_budgets
    DROP CONSTRAINT project_budgets_user_task_unique;

ALTER TABLE public.project_budgets
    ALTER COLUMN todoist_task_id DROP NOT NULL;

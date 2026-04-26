-- FEAT-7: add optional scheduling hint to rhythms.
-- Nullable, no default. CHECK enforces 80-char max at DB level.

ALTER TABLE public.rhythms
  ADD COLUMN description text CHECK (char_length(description) <= 80);

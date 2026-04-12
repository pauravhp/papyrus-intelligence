-- Add anthropic_api_key column (encrypted, same pattern as groq_api_key)
ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS anthropic_api_key text;

-- Expose set_config as an RPC so PostgREST can call it
-- (referenced in api/db.py set_encryption_key() but not yet in any migration)
CREATE OR REPLACE FUNCTION public.set_encryption_key(key text)
RETURNS void LANGUAGE sql SECURITY DEFINER AS $$
    SELECT set_config('app.encryption_key', key, true);
$$;

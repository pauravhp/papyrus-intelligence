"""
Supabase client (secret key — sb_secret_... format).

The secret key bypasses RLS — use only for server-side writes where the
user_id is already verified by the JWT dependency. Never expose this key
to the client.

Encryption key injection
------------------------
Before any Supabase RPC or query that touches encrypted columns
(todoist_api_key, groq_api_key, google_credentials), call:

    set_encryption_key()

This runs `SELECT set_config('app.encryption_key', <key>, true)` in the
current session, so the encrypt_field / decrypt_field SQL functions can
read it via current_setting('app.encryption_key').

The `is_local=true` flag scopes the setting to the current transaction,
which is appropriate for per-request connection pooling.
"""

from supabase import Client, create_client

from api.config import settings

supabase: Client = create_client(
    settings.SUPABASE_URL,
    settings.SUPABASE_SECRET_KEY,
)


def set_encryption_key() -> None:
    """
    Inject the encryption key into the current Postgres session so that
    encrypt_field() / decrypt_field() SQL functions can use it.

    Call this before any RPC or query that reads or writes an encrypted column.

    REQUIRES a public wrapper function in Supabase (Postgres built-in set_config
    is not exposed via PostgREST). Add this migration before using encrypted columns:

        CREATE OR REPLACE FUNCTION public.set_encryption_key(key text)
        RETURNS void LANGUAGE sql SECURITY DEFINER AS $$
            SELECT set_config('app.encryption_key', key, true);
        $$;

    Until that migration is applied, this is a no-op (logged as a warning).
    """
    try:
        supabase.rpc(
            "set_encryption_key",
            {"key": settings.ENCRYPTION_KEY},
        ).execute()
    except Exception as exc:
        print(f"[db] set_encryption_key skipped (migration not applied?): {exc}")

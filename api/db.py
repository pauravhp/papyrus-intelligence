"""
Supabase client (secret key — sb_secret_... format).

The secret key bypasses RLS — use only for server-side writes where the
user_id is already verified by the JWT dependency. Never expose this key
to the client.

Note: The pgcrypto encrypt_field/decrypt_field functions and the per-user
credential columns (todoist_api_key, groq_api_key, anthropic_api_key) were
removed in migrations 006–007. google_credentials is stored as plain jsonb.
ENCRYPTION_KEY is still required — used for HMAC state signing in OAuth flows.
"""

from supabase import Client, create_client

from api.config import settings

supabase: Client = create_client(
    settings.SUPABASE_URL,
    settings.SUPABASE_SECRET_KEY,
)

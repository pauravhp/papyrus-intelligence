-- =============================================================================
-- 006_app_layer_encryption.sql
--
-- Switch from DB-layer pgcrypto encryption to application-layer encryption.
-- The Python backend now encrypts/decrypts with cryptography.fernet before
-- reading or writing the DB. The DB stores opaque text blobs and has no
-- knowledge of the key or the encryption scheme.
--
-- What this migration does:
--   1. Drop the encrypt_field / decrypt_field / set_encryption_key SQL functions
--      (no longer needed — key must never appear in DB query parameters or logs)
--   2. Clear the pgcrypto-encrypted credential columns so the app can write
--      fresh Fernet-encrypted values on next setup
-- =============================================================================

-- Drop encryption functions
DROP FUNCTION IF EXISTS public.encrypt_field(text);
DROP FUNCTION IF EXISTS public.decrypt_field(text);
DROP FUNCTION IF EXISTS public.set_encryption_key(text);

-- Clear old pgcrypto-encrypted credentials (dev DB only — re-enter via /onboard)
UPDATE public.users
SET
    groq_api_key      = NULL,
    anthropic_api_key = NULL,
    todoist_api_key   = NULL;

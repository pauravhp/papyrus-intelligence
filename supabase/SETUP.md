# Supabase Setup

## How to apply the migration

### Prerequisites

```bash
npm install -g supabase
supabase login
```

### Steps

1. **Create a Supabase project** at https://supabase.com/dashboard.
   Note your project ref (e.g. `abcdefghijklmnop`).

2. **Link the local repo to your project:**
   ```bash
   supabase link --project-ref <your-project-ref>
   ```

3. **Push the migration:**
   ```bash
   supabase db push
   ```
   This applies `supabase/migrations/001_initial.sql` to your remote Postgres instance.

   Alternatively, paste the file contents directly into the Supabase SQL editor.

---

## Encryption key setup (required before first user signup)

API keys (`todoist_api_key`, `groq_api_key`) and `google_credentials` are encrypted
at rest using `pgcrypto`'s `pgp_sym_encrypt`. The symmetric passphrase is never
stored in the database — the FastAPI backend sets it per-session via:

```sql
SET app.encryption_key = '<secret>';
```

To wire this up:

1. Go to **Supabase dashboard → Settings → Vault** and create a secret named
   `app_encryption_key` with a strong random value.

2. In the FastAPI startup code, fetch this secret via the Supabase Management API
   or environment variable and set it on each database connection before any
   `encrypt_field` / `decrypt_field` call.

Do **not** store the encryption key in `.env` or commit it anywhere.

---

## CLI local dev

The CLI continues to use `data/schedule.db` (SQLite) — no Supabase dependency
for local development. The `user_id` column does not exist in the SQLite schema;
all per-user scoping in the CLI is implicit (single user, single file).

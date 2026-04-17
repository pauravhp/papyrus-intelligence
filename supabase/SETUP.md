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

## Encryption / credentials

`google_credentials` is stored as plain `jsonb` in the `users` table. No pgcrypto encryption is applied to it (deferred — see LEARNINGS.md for rationale).

The `ENCRYPTION_KEY` env var is still required, but it is used exclusively for **HMAC state signing in the Google OAuth flow** — not for database-level encryption.

The `encrypt_field` / `decrypt_field` / `set_encryption_key` SQL functions and the `todoist_api_key`, `groq_api_key`, `anthropic_api_key` columns were all removed in migrations 006–007. There is no per-user LLM key storage.

---

## CLI local dev

The CLI continues to use `data/schedule.db` (SQLite) — no Supabase dependency
for local development. The `user_id` column does not exist in the SQLite schema;
all per-user scoping in the CLI is implicit (single user, single file).

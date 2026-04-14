-- Temporary column to carry the PKCE code_verifier between the OAuth start
-- and callback requests. Cleared immediately after token exchange succeeds.
alter table users add column if not exists oauth_code_verifier text;

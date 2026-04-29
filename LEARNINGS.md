# LEARNINGS.md — papyrus-intelligence

API gotchas and architectural decisions. Read before touching any API client code. Ported from schedule-for-me where noted.

---

## Todoist API

**Base URL:** `https://api.todoist.com/api/v1/` — REST v2 and Sync v9 both return 410 Gone.

**Writes use POST, not PATCH.** `PATCH /api/v1/tasks/{id}` → 405. Use `POST /api/v1/tasks/{id}` with a partial body.

**Task list responses are paginated.** v1 returns `{"results": [...], "next_cursor": ...}` — always use `_get_all_pages()`. Filter strings (`!date | today | overdue`, `@label`, `p1`) are unchanged from v2.

**Priority is inverted.** API: 4=P1, 3=P2, 2=P3, 1=P4. A new task with no priority set has `priority: 1` (P4/lowest). Use `_PRIORITY_LABEL = {4:"P1", 3:"P2", 2:"P3", 1:"P4"}` for display.

**Labels have no `@` prefix in API responses.** `@30min` in the UI → `"30min"` in the API. All in-code comparisons must omit the `@`. `context.json` uses `@label` for human readability only.

**Duration is read from labels, not the native field.** `DURATION_LABEL_MAP` in `todoist_client.py` maps `"30min"` → 30, etc. The matched label is stripped before passing to the LLM.

**Clearing due dates — field matters:**

- To fully remove due: `{"due_string": "no date"}` — removes date + datetime.
- To clear time only: `{"due_datetime": null}` — may leave a date-only entry, which `_parse_task` still reads as a `due_datetime`.
- `{"due": null}` is **silently ignored** — not a valid update field. Tasks retain their due after the call.

**"today & completed" filter returns active tasks too.** Unreliable for review — abandoned. Current approach: task_history as authoritative list, `GET /tasks/{id}` per task for status (404 = completed).

**`sync/v9/activity/get` is still live** despite sync v9/sync being deprecated. Reserved for Phase 7 habit tracking only — it returns stale historical events that cause false positives in real-time review.

**`due_datetime` only — no `duration` field.** papyrus-intelligence targets  
 Free-tier Todoist users. Never write `duration`/`duration_unit` to tasks.  
 Write `due_datetime` for task organisation only. GCal events are written directly.

---

## Architecture

**`compute_free_windows()` uses `max(morning_buffer, ceil5(now))` when `target_date == today`.** Added `now_override: datetime | None` parameter. If `start_override` is None and `target_date == date.today()` and `effective_now > effective_start`, the effective start is advanced to `ceil(now, 5min)` (same rounding algorithm as `--add-task`: `extra = (5 - minute % 5) % 5`, +5 if exactly on boundary with sub-minute precision). The `now_override` parameter is used in tests to inject a fixed "current time" without mocking. **Does not apply to tomorrow or past dates** — only `target_date == date.today()` triggers. `start_override` (used by `--add-task`) takes precedence and bypasses this check entirely.

**Four task buckets in `--plan-day`:**

- `already_scheduled` — has `due_datetime` on target_date → blocks time, shown, skipped by LLM
- `pinned_other_day` — has `due_datetime` on another date → shown, skipped entirely
- `schedulable` — has `duration_minutes`, no `due_datetime` → passed to LLM
- `skipped` — no `duration_minutes` → listed with duration label hint

---

## Scheduling Rules

**`context.json` is authoritative over CLAUDE.md prose.** Weekend cutoff is 13:00 (not noon). Flamingo buffer is 15min each side (not 30min). Always read from structured `context.json` fields at runtime.

**GCal: query all calendars, not just "primary".** Call `calendarList().list()` first, then query each calendar. Events on secondary calendars (shared, work) are otherwise invisible to the scheduler.

---

## Model

**Default model: `claude-haiku-4-5-20251001` (Anthropic SDK).** All LLM calls use the server-side `ANTHROPIC_API_KEY` from settings. No per-user keys, no BYOK, no Groq fallback. The key columns (`anthropic_api_key`, `groq_api_key`) were dropped in migrations 006–007.

---

## Phase-3 Schema Additions (2026-04-08)

**`excluded` references in ON CONFLICT DO UPDATE.** `excluded.column_name` refers to the value that _would have been inserted_ (i.e., the new value), while `table_name.column_name` refers to the current value on disk. This lets you compare old vs new `scheduled_at` to detect reschedules and compute ratios against the pre-existing `estimated_duration_mins`.

**Supabase Postgres migrations go in `supabase/migrations/`.** Never use  
 SQLite ALTER TABLE patterns. Schema changes are SQL migration files,  
 applied via `supabase db push`.

---

## Google OAuth Flow (2026-04-11)

**Browser-initiated OAuth can't use Bearer headers — pass JWT as `?token=` query param.** When the frontend navigates `window.location.href = /auth/google?token=<jwt>`, no custom headers travel with the request. The route validates the JWT via JWKS immediately, signs the user_id into a HMAC state param, and drops the token. The JWT never touches Google.

**HMAC state format: `user_id:timestamp:sha256_hex`.** UUID contains only hex+hyphens (no colons), timestamp is digits, HMAC hex is 0-9a-f. `split(":")` gives exactly 3 parts cleanly. Timestamp lets the backend reject stale states (>10 min). `hmac.compare_digest` prevents timing attacks on the signature check.

**`prompt="consent"` on the authorization URL forces a new refresh_token every grant.** Without it, Google only returns a refresh_token on the very first grant. Subsequent grants return only an access_token, breaking token refresh after expiry.

**`Credentials.from_authorized_user_info(creds_dict)` + override client credentials.** `to_json()` embeds client_id/secret in the stored JSON. On load, we override `creds._client_id` and `creds._client_secret` from settings to ensure config changes propagate without re-auth. The private attribute names are `_client_id` and `_client_secret` (google-auth 2.x).

**`google_credentials` stored as plain jsonb for now.** The column is `jsonb` in the Supabase schema. pgcrypto `encrypt_field()` returns a base64 text string which is not valid JSON — the column would need to be changed to `text` for encrypted storage. Deferred; treat as a pending migration.

**`get_events()` accepts an optional `service` arg — CLI path unchanged.** `service=None` falls back to `_get_calendar_service()` which reads `token.json`. All existing CLI commands, tests, and the `--check` command are unaffected. API path passes a pre-built service built from Supabase-stored credentials.

**`GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` added to Settings.** Pulled from `credentials.json` at the project root. Both are required at startup. Add to `.env` before running the API.

---

## Frontend Auth Setup (2026-04-10)

**`NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` replaces `NEXT_PUBLIC_SUPABASE_ANON_KEY`.** The old anon key was a long-lived JWT tied to the project's JWT secret — rotating the secret could cause app-wide downtime. The new publishable key (`sb_publishable_...`) is non-JWT and can be rotated independently. Both work during the transition period; always use `PUBLISHABLE_KEY` for new projects.

**`getClaims()` not `getSession()` for server-side auth.** `getSession()` reads the cookie as-is — no cryptographic validation, can be spoofed. `getClaims()` validates the JWT against the project's JWKS endpoint (RS256/ES256) or falls back to `getUser()` for symmetric keys. Safe for middleware and Server Components. `data` shape: `{ claims: JwtPayload; header: JwtHeader; signature: Uint8Array } | null` — check `data?.claims`, not `data?.claims` directly from destructuring.

**`utils/supabase/middleware.ts` must return both `supabase` and `supabaseResponse`.** The Supabase-provided template returns only `supabaseResponse`. To call `getClaims()` in `middleware.ts`, we need the `supabase` client from the same closure (same cookie `setAll` binding). Modified the utility to `return { supabase, supabaseResponse }`.

**Auth callback route at `/auth/callback`.** When email confirmation is enabled, Supabase sends a link that redirects to `<origin>/auth/callback?code=<code>`. The route handler calls `supabase.auth.exchangeCodeForSession(code)` and redirects to `/dashboard`. Without this route, email confirmation silently fails.

**`create-next-app@latest` installed Next.js 16.2.3, not 14.** `npx create-next-app@latest` always installs the current latest — specify `@14` in the command to pin a version. Next.js 16 is compatible with all patterns used here; `cookies()` must be awaited (already the correct pattern for 15+).

**Next.js 16 renamed `middleware.ts` → `proxy.ts`, `middleware()` → `proxy()`.** The functionality is identical; only the file name and exported function name changed. A `middleware.ts` file still works but emits a deprecation warning at build time. Always use `proxy.ts` for Next.js 16+ projects. The `config` export with `matcher` is unchanged.

---

## --onboard Stage 1 (2026-04-10)

**LLM correctly identifies colorId semantics from event names alone.** Even without explicit buffer/type hints, the model correctly mapped colorId 4 (short ~42min events with "Lab Meeting", "call" in names) → meeting_or_call and colorId 5 (long ~170min events) → focus_block_or_event.

**Draft collision detection: if Stage 1 draft exists with `pending_stage_2_qa` status, skip re-scan.** This prevents accidentally wiping an answered Q&A draft by re-running `--onboard`. To force a re-scan, user must delete `context.json.draft` first.

---

## --onboard context.template.json (2026-04-10)

**`context.template.json` is the draft base, not `context.json`.** `_build_draft_context` now takes `template` (loaded from `context.template.json`) as its first argument. The live `context.json` is only read for scan credentials (`timezone`, `calendar_ids`) — it never feeds into the draft structure. This means onboarding always starts clean regardless of what the existing user's config contains.

**`timezone` and `calendar_ids` are scan credentials only.** They come from `context.json` (with `"America/Vancouver"` fallback for timezone) and are used solely to call `get_events()`. They do NOT appear in the draft base — the template has `user.timezone: null` and `calendar_ids: []`. The LLM prompt still receives the live context via `build_onboard_prompt(patterns, context)` so it can see current config for reference, but the draft base is always the template.

**Template fields that stay null until Stage 2/3:** `user.name`, `user.timezone`, `calendar_ids`, `sleep.default_wake_time`, `sleep.default_sleep_time`, `sleep.first_task_not_before`, `sleep.weekend_nothing_before`, `calendar_rules.flamingo.color_id`, `calendar_rules.banana.color_id`, `daily_blocks`, `projects`. Fields with universal defaults (`morning_buffer_minutes: 90`, `label_vocabulary`, `rules`, `scheduling`) are pre-populated.

---

## --onboard Stage 2 (2026-04-10)

**`_set_nested` silently skips unknown paths.** If the LLM produces a `field` like `current_sleep_config.no_tasks_after` that doesn't match the draft structure, `_set_nested` returns without writing anything. This is intentional — never inject unknown keys into the draft.

**Numeric coercion for `_minutes` / `_min` fields.** If the field path ends with `_minutes` or `_min` and the answer string parses as an integer, it is stored as `int` (not string). This keeps the draft type-consistent with context.json.

---

## --onboard Stage 3 (2026-04-10)

**Template draft has `user.timezone: null` — inject scan_timezone before calling `compute_free_windows()`.** `compute_free_windows` reads `context.get("user", {}).get("timezone", "America/Vancouver")`. A null value coerces to a string `"None"` which `ZoneInfo` rejects. Fix: `_run_stage_3` injects `scan_timezone` into the working copy's `user.timezone` when the draft value is null.

**Promotion strips `_onboard_draft` and removes `context.json.draft`.** `draft_path.unlink()` removes the draft file after a clean write to `context.json`. `shutil.copy2` (not `shutil.copy`) is used for backup — it preserves file metadata. `context.json.bak` is overwritten on each onboard run so there's always at most one backup.

---

## Landing Page + 3D Visual System (2026-04-11)

**Cal Sans is not on Google Fonts — load via `@font-face` CDN.** The spec says "Cal Sans (Google Fonts)" but Cal Sans is a Cal.com proprietary font, not available via `next/font/google`. It's loaded via `@font-face` in `globals.css` from the calcom GitHub CDN (`raw.githubusercontent.com/calcom/font/main/fonts/CalSans-SemiBold.woff2`). For production, the woff2 should be copied into `public/fonts/` and referenced locally to avoid external CDN dependency.

**Tailwind v4 has no `tailwind.config.js` — customise in `globals.css`.** Adding custom colors requires: (1) define CSS vars in `:root`, (2) register them as design tokens in `@theme inline { --color-* }`. Custom utilities (`font-display`, etc.) go in `@layer utilities`. No JS config file exists or is needed.

**`@react-three/fiber` v9 + React 19 requires `--legacy-peer-deps`.** R3F v9 declares `react: ^18` in peer deps but works with React 19. Install with `--legacy-peer-deps` to bypass the peer check. Same applies to `@react-three/drei`.

**`framer-motion-3d` is deprecated.** npm warns "Package no longer supported" for `framer-motion-3d`. 3D animations for this project use `@react-three/drei`'s `<Float>` component instead; `framer-motion` is only used for 2D scroll animations (`whileInView`, `initial/animate`). `framer-motion-3d` was installed per spec but is effectively unused.

**OrbField must be `dynamic`-imported with `ssr: false` even though the file has `'use client'`.** The `'use client'` directive prevents SSR of the component tree, but Next.js will still attempt to import the module at build time to extract metadata. `@react-three/fiber`'s `Canvas` references browser globals (`window`, `WebGLRenderingContext`) that cause build errors if the module is evaluated server-side. Fix: in `LandingClient.tsx`, `const OrbField = dynamic(() => import('./OrbField'), { ssr: false })`.

**Deterministic RNG keeps orb positions stable across re-renders.** Using `Math.random()` inside `useMemo` means positions change on every hot-reload. A seeded LCG (`seed * 16807 % 2147483647`) produces identical orb layouts every run. Pass `seed=42`; results are visually varied but reproducible.

**GCal token refresh scope must match the originally-granted scope.** Refreshing a stored token with a *wider* scope than was granted (e.g. adding `calendar.events` to a token originally granted `calendar.readonly`) causes `invalid_scope: Bad Request`. The onboard stage1 route only reads events — use `SCOPES` (readonly) for token refresh there. Only use `WRITE_SCOPES` in the chat endpoint where write access is actually needed. The user must re-run the OAuth flow (`/auth/google`) to obtain a token with write scope.

**Camera parallax inside R3F: pass a plain object ref, not `React.RefObject<T>`.** `useFrame` runs inside the Canvas renderer, outside React's commit phase. Passing a `mouseRef` created by `useRef<{x,y}>({x:0,y:0})` works correctly — it's a mutable object shared between the event listener (outer component) and `useFrame` (inner renderer). Type the prop as `{ current: { x: number; y: number } }` (not `React.RefObject<T>`) to avoid the readonly constraint TypeScript places on `RefObject.current`.

---

## Project Budgets — ReAct Agent Integration (2026-04-12)

**`schedule_log` always records `date.today()`, not the target schedule date.** In `execute_confirm_schedule` (agent_tools.py), `"schedule_date": date.today().isoformat()` uses today regardless of what date was scheduled. When a user confirms tomorrow's schedule, the log row is stored under today — `execute_get_status` (which queries by today) will find it immediately, but when tomorrow arrives, it won't. Fix: include `schedule_date` in the schedule dict from `schedule_day` and forward it through `execute_confirm_schedule`.

**`proj_` task IDs are the delimiter between Todoist tasks and synthetic project tasks.** Any `task_id` starting with `proj_` in `execute_confirm_schedule` skips the Todoist `schedule_task` call. GCal events are still created for all tasks. Budget decay is manual-only via `log_project_session`.

**`src/queries/budgets.py` has orphaned SQLite CRUD functions.** After adding `api/services/project_service.py`, the old SQLite functions (`create_project_budget`, `get_all_active_budgets`, `decrement_budget`, etc.) in `budgets.py` are unreachable dead code. Only `compute_deadline_pressure` from that file is still imported. Clean up those SQLite functions in a future session.

**Patching module-level imports in agent_tools.py requires the import at module scope.** `patch("api.services.agent_tools.get_active_projects", ...)` only works if `get_active_projects` is imported at the top of `agent_tools.py`, not inside a function. Inline imports (`from x import y` inside a function) create a local name that can't be patched via the module path.

## BUG-2 — Todoist OAuth re-consent (investigated 2026-04-15)

**Todoist has no OAuth parameter to force re-consent.** The `force_approval` parameter does not exist in Todoist's OAuth spec (documented params: `client_id`, `scope`, `state`, optional `redirect_uri`). Todoist silently ignores unknown query params. Repeat authorizations auto-approve server-side without showing the consent screen — this is Todoist's intentional design.

**Account switching requires manual steps.** To connect a different Todoist account, users must: (1) go to Todoist Settings → Integrations → disconnect the app, (2) return and re-authorize. The correct product fix is a "Disconnect Todoist" button in the frontend that clears `todoist_oauth_token` in Supabase, with instructions to revoke access in Todoist settings first.

---

## FEAT-2 — Today view always shows live GCal events (2026-04-15)

**`get_today_view` builds the GCal service inline, same pattern as `_load_user_context` in `chat.py`.** `build_gcal_service_from_credentials(creds, client_id, client_secret)` returns `(service, refreshed | None)`. Write refreshed creds back to Supabase immediately.

**`gcal_event_ids` in `schedule_log` is stored as a JSON string**, not a native Postgres array. Must `json.loads()` it before iterating. Use `_papyrus_ids()` helper with try/except fallback to empty set.

**`_parse_day` null logic change**: old gate was "no `proposed_json` → None". New gate: "no schedule AND no GCal events → None". A gcal-only day must return a dict with `scheduled: []` so the frontend renders the GCal layer.

**`hasGcal` in `DayColumn.tsx` must include `all_day_events`**, not just `gcal_events`. Omitting it caused the empty-state message to show alongside all-day pills for days with holidays/OOO but no scheduled tasks.

**Three sequential GCal API calls per `/api/today` load** (one per day). Accepted v1 tradeoff — users open this view once or twice a day. No caching needed yet.

---

## BUG-3 — GCal calendar selection (discovered 2026-04-16)

**`get_events` originally only queried `"primary"` + an explicit `calendar_ids` whitelist from Supabase config.** The whitelist was always empty (not populated during onboarding), so only primary calendar was queried — missing events in non-primary calendars (e.g. work meetings in a shared org calendar).

**Fix applied**: `_get_user_calendar_ids(service)` auto-discovers all calendars the user owns/writes via `calendarList().list()`, bypassing the whitelist entirely. **Side effect**: this now pulls ALL user calendars including ones the user may not want (e.g. a hobby calendar that pollutes the scheduler).

**Correct long-term fix**: let users select which calendars to read from (source calendars) and which to write to (target calendar for new events). These are different choices — a user may want to read from both their work and personal calendars but write new events only to personal. Store selections as `source_calendar_ids` and `target_calendar_id` in Supabase config. The current `_get_user_calendar_ids` approach is a useful fallback/default but needs a UI for explicit control.

---

## BUG-1 — schedule_day / GCal integration (fixed 2026-04-15)

Three issues found and fixed together:

1. **Positional arg mismatch** (`agent_tools.py`): `compute_free_windows(..., scheduled_tasks)` passed the list as `late_night_prior`. Fix: keyword arg `scheduled_tasks=scheduled_tasks`.
2. **No post-LLM validation**: LLM-proposed times were never checked against free windows — a hallucinated slot inside a blocked interval would get confirmed on top of a GCal event. Fix: filter `scheduled` items outside all free windows into `pushed` after `schedule_day` returns.
3. **LLM had no event context**: prompt only showed opaque window strings. Fix: pass `events` to `_build_prompt`; add `CALENDAR EVENTS (already blocked)` section so the LLM reasons around actual meetings.

---

## 2026-04-28 — Driver.js spike for migration assistant DemoTour

**Verdict:** TENTATIVE GO (pending manual browser verification by the user).

**Why:** Driver.js v1.x compiles cleanly against the project's Next.js setup and offers the three behaviours we need: anchored highlight + popover, centered popover (no anchor), and explicit close-button handling. The wrapper at `frontend/components/DemoTour.tsx` exposes a 4-prop surface (`step`, `anchor`, `variables`, `onSkip`) which is the minimum needed for Tasks 12-13. Bundle size is ~6 KB gzipped — acceptable.

**Manual smoke still owed before Task 12 ships:**
1. Bubble renders centered (no anchor).
2. Bubble anchors over a target element via CSS selector.
3. "I'll explore on my own" close button fires `onSkip`.
4. Variable substitution works (`{tasksN}` → "12").
5. Step transitions cleanly (changing prop `step` destroys old bubble, mounts new without orphan).

**If any fail** during Task 12 integration: replace `DemoTour.tsx` with a custom portal-rendered component (~half-day extra) and update this entry.

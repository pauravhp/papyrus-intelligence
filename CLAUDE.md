# CLAUDE.md — papyrus-intelligence

## Worktrees

Worktree directory: `../` (sibling directories, e.g. `../papyrus-intelligence-<branch-name>`)

## What This Is

A scheduling coach and personal productivity hub. Three moments:

- **Morning:** Chat to plan your day with natural language context ("plan light today, roommate isn't doing well")
- **Mid-day:** Replan gracefully when things slip — resilience over precision
- **Weekly:** Achievement narrative — what you built, not what you missed

Hub-and-spoke:

- **Todoist** → passive input (mobile capture only)
- **This app** → active hub (all scheduling happens here)
- **GCal** → passive output (app writes events directly)

No Todoist Pro. Direct GCal writes. Server-side Anthropic key for all LLM calls — no user API keys required.

---

## Architecture — ReAct Agent

**The LLM orchestrates. Code enforces. Writes are human-gated.**

User: "plan my day"  
 Agent → get_tasks() → get_calendar() → schedule_day() → ScheduleCard shown  
 User: "looks good"  
 Agent → confirm_schedule() → GCal events written + Todoist due_datetimes set

DO NOT build a hardcoded pipeline. No pack_schedule(). No enrich→order→pack.  
 The LLM assigns tasks to times. Python provides free windows and enforces hard constraints.

---

## Stack

- Python 3.10+ / FastAPI
- Next.js 15 / TypeScript / app router
- Supabase (Postgres + Auth + encrypted credential storage)
- Anthropic SDK (Claude Haiku default) — server-side key for all LLM calls
- Google Calendar API (read + write, `calendar.events` scope)
- Todoist REST API v1 (read + `due_datetime` writes only, no Pro features)

---

## Core Rules

**Rule 1: LLM orchestrates, code enforces.**  
 Hard constraints (sleep hours, cutoffs, GCal buffers) enforced in Python.
LLM gets pre-computed free windows as guidance, not walls.

**Rule 2: Writes are human-gated.**  
 `confirm_schedule` is the only tool that writes externally.  
 Only called after user approves the proposed schedule.

**Rule 3: Tools are the unit of work.**  
 Each tool is independently testable. No tool has side effects unless it's a write tool.  
 Tools return structured data, not strings.

**Rule 4: One LLM call for scheduling.**  
 `schedule_day()` = single call. Input: tasks + free windows + context + context_note.  
 Output: proposed schedule with reasoning. No multi-step pipeline.

**Rule 5: Direct GCal writes.**  
 Never rely on Todoist's GCal sync. Write GCal events directly.  
 Set due_datetime in Todoist for task organisation only.

**Rule 6: Server-side Anthropic key for all LLM calls.**  
 All LLM operations — scheduling, chat, onboarding scan — use `settings.ANTHROPIC_API_KEY`.  
 There is no per-user key. No BYOK. No encrypted key columns in the DB.

**Rule 7: JSON validation on all LLM outputs.**  
 try/except + parse. Retry once. Log full prompt on double failure.

---

## Agent Tools

| Tool               | R/W | Purpose                                   |
| ------------------ | --- | ----------------------------------------- |
| `get_tasks`        | R   | Todoist tasks with filter                 |
| `get_calendar`     | R   | GCal events (user-selected calendars)     |
| `schedule_day`     | R   | Inner LLM call → proposed schedule        |
| `confirm_schedule` | W   | Write GCal events + Todoist due_datetimes |
| `push_task`        | W   | Clear due + add comment                   |
| `get_status`       | R   | Today's confirmed schedule from Supabase  |
| `onboard_scan`     | R   | 14-day GCal pattern scan                  |
| `onboard_apply`    | W   | Apply Q&A answers to draft config         |
| `onboard_confirm`  | W   | Promote draft → live config               |

---

## Coaching Rules

- One nudge max per conversation (e.g. "you haven't set a deadline on this project")
- Never raised again if dismissed
- Toggleable off in user settings
- Surfaces in weekly story + in conversation — never as a popup

---

## Testing

- Write tests before implementation (`superpowers:test-driven-development`)
- Every tool's Python implementation has unit tests
- No real API calls in unit tests — mock TodoistClient, get_events, LLM calls
- Run: `source venv/bin/activate && python3 -m pytest tests/ -v`
- Use `superpowers:verification-before-completion` before marking any step done

---

## Deployment

**Frontend:** Vercel (Next.js, GitHub-connected auto-deploy)
**Backend:** Hetzner VPS (`5.78.200.61`), systemd + Caddy reverse proxy
**Database:** Supabase Cloud (shared between dev and prod)

### Port Mapping (canonical — dev Mac and VPS match)

| Project                | Host port (dev Mac) | Host port (VPS) | Caddy hostname               |
|------------------------|---------------------|-----------------|------------------------------|
| `papyrus-intelligence` | `8001`              | `8001`          | `papyrus.5-78-200-61.nip.io` |
| `reed-resume-engine`   | `8000`              | `8000`          | `5-78-200-61.nip.io`         |

Papyrus backend runs on **8001** everywhere. Start locally with
`uvicorn api.main:app --reload --port 8001`. Frontend stays on `3000`.

Both projects share the same Hetzner VPS. Caddy routes by hostname. Each project
has its own systemd unit, venv, and `.env` file.

### Backend Env Vars (VPS)

`SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `ENCRYPTION_KEY`, `GOOGLE_CLIENT_ID`,
`GOOGLE_CLIENT_SECRET`, `TODOIST_CLIENT_ID`, `TODOIST_CLIENT_SECRET`,
`ANTHROPIC_API_KEY`, `FRONTEND_URL` (set to Vercel URL),
`BACKEND_URL` (set to public Caddy hostname, e.g.
`https://papyrus.5-78-200-61.nip.io` — used to build OAuth callback URIs;
must match the redirect URIs registered in Google Cloud Console + Todoist
app settings), `POSTHOG_API_KEY`, `BETA_ALLOWLIST` (comma-separated emails),
`BACKEND_CORS_ORIGINS` (comma-separated origins).

### Frontend Env Vars (Vercel)

**Public (NEXT_PUBLIC_, baked into bundle):**
`NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`,
`NEXT_PUBLIC_POSTHOG_HOST`, `NEXT_PUBLIC_POSTHOG_KEY`,
`NEXT_PUBLIC_API_URL` (set to `https://papyrus.5-78-200-61.nip.io`).

**Server-only (no NEXT_PUBLIC_ prefix):**
`RESEND_API_KEY`, `ADMIN_USER_ID` (your Supabase user UUID, for /admin gating),
`POSTHOG_PERSONAL_API_KEY`, `POSTHOG_PROJECT_ID`.

---

## Session Protocol

- Planning: use `superpowers:writing-plans`, track in `task_plan.md`
- Implementation: one item from `task_plan.md` per session, TDD, verify, commit
- Append API gotchas and decisions to `LEARNINGS.md` after each session
- Use `superpowers:requesting-code-review` before moving to the next step

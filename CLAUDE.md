# CLAUDE.md

## Scheduling Agent — Claude Code Context Document

Place this file at the project root. Claude Code reads it automatically at session start.

---

## 1. What This Project Is

A personal AI scheduling agent that reads Google Calendar + Todoist, reasons about them via a multi-step LLM pipeline (Groq/Llama), proposes a daily schedule respecting personal rules, gets user confirmation, and writes back to Todoist via the Sync API. Google Calendar sync then handles calendar block creation automatically.

The agent is the intelligence layer. Todoist is the interface the user already lives in. The goal is to make Todoist smarter, not to replace it.

---

## 2. Language & Stack

- Python 3.10+
- SQLite via the built-in `sqlite3` module (`data/schedule.db`)
- Google Calendar API (`google-api-python-client`)
- Todoist REST API v2 + Sync API v9
- Groq API (`groq` Python SDK). Model for Step 1 Enrich: `llama-3.3-70b-versatile`. Model for Step 2 Schedule: `llama-3.3-70b-versatile`.
- `python-dotenv` for secrets
- CLI via `argparse` — flags: `--plan-day`, `--review`, `--add-task`, `--check`
- `productivity_science.json` — pre-compiled research reference (see Section 9)

---

## 3. Project Structure

```
scheduling-agent/
├── CLAUDE.md
├── README.md
├── .env                      # secrets, never commit
├── credentials.json          # GCal OAuth creds, never commit
├── token.json                # GCal OAuth token, never commit
├── context.json              # personal scheduling rules and label vocab
├── productivity_science.json # pre-compiled research (never re-fetch at runtime)
├── main.py                   # CLI entry point
├── src/
│   ├── calendar_client.py    # Google Calendar API wrapper
│   ├── todoist_client.py     # Todoist REST + Sync API wrapper
│   ├── scheduler.py          # free window calculator, constraint engine
│   ├── llm.py                # Groq calls, prompt templates, chain
│   ├── db.py                 # SQLite setup and queries
│   └── models.py             # typed dataclasses
├── data/
│   └── schedule.db           # SQLite database (gitignored)
├── snapshots/
│   └── latest.json           # last confirmed schedule snapshot (gitignored)
└── tests/
    └── test_scheduler.py     # unit tests for free window calculator
```

---

## 4. Key Architectural Rules — DO NOT VIOLATE

**Rule 1: Constraints in code, judgment in LLM.**
The LLM never receives raw calendar events. It only receives pre-computed free windows. Never ask the LLM to figure out what time is free — compute that in `scheduler.py` first.

**Rule 2: LLM handles judgment only.**
Task ordering, slot assignment within free windows, project inference, energy/circadian reasoning, momentum sequencing. It does not enforce hard rules — code does that.

**Rule 3: Diff before writing.**
Always compare new schedule against `snapshots/latest.json`. Only write tasks that actually changed. Never overwrite unchanged tasks.

**Rule 4: Batch writes via Sync API.**
All Todoist writes use Sync API v9 in a single HTTP call. Individual task reads use REST API v2.

**Rule 5: Google Calendar is read-only.**
Never write to GCal directly. Todoist's native GCal sync handles calendar block creation automatically once `due_datetime` and `duration` are set on a task.

**Rule 6: All LLM outputs must be valid JSON.**
Wrap every LLM call in `try/except` with JSON parse validation. Retry once on failure. Log the full prompt if retry also fails.

**Rule 7: Use Todoist filter syntax for task fetching.**
Do not fetch all tasks and filter in Python. Push the query to Todoist:

- Daily planning: `"!date | today | overdue"`
- At-risk tasks: `"p1 & due before: +2 days"`
- Inbox triage: filter by `project_id` matching inbox ID
- In-progress: `"@in-progress"`

**Rule 8: Never re-fetch `productivity_science.json` at runtime.**
This file is pre-compiled research. It is loaded once at startup and injected into LLM prompts as static context. It never makes an external call at scheduling time.

---

## 5. Todoist — Full Feature Usage

This project uses Todoist as more than a task store. Use all of the following:

### Labels as scheduling metadata

Defined in `context.json` under `label_vocabulary`. The scheduler reads these as hard constraints before the LLM step:

- `@deep-work` — schedule in high-focus windows only, never adjacent to meetings without buffer
- `@admin` — low-cognitive, batch in afternoon
- `@waiting` — never auto-schedule, surface in weekly review only
- `@quick` — under 15min, batch into transition gaps between blocks
- `@focus` — needs uninterrupted environment
- `@in-progress` — partially done, higher urgency than unstarted same-priority tasks
- `@recurring-review` — weekly review only, not daily plan

### Sections for task state within projects

Each project uses sections: **This Week / Backlog / Waiting**. When the agent schedules a task, it moves it to "This Week". When pushed to next week, it moves to "Backlog". When `@waiting`, it moves to "Waiting". This gives the user a live Kanban view inside Todoist that mirrors agent decisions.

### Filter syntax for all task queries

Never fetch-all. Always use Todoist filter strings via REST API v2 `GET /tasks?filter=<string>`.

### Task comments as audit trail

When the agent reschedules a task, it writes a comment:
`"Rescheduled from Wed 3pm → Thu 9:30am. Reason: supervisor call conflict."`
Uses `POST /comments`.

### Reminders on P1 blocks (Phase 3+)

Set a 10-minute reminder before any scheduled P1 task block via `POST /reminders`. Requires Pro account (user has this).

### Activity log for habit learning (Phase 7)

Use `GET https://api.todoist.com/sync/v9/activity/get` to read actual completion timestamps. More accurate than self-reported end-of-day capture.

### Official Todoist MCP (future/multi-user phase)

Doist maintains an official MCP at `https://ai.todoist.net/mcp`. When the project gets a web backend, expose scheduling logic through this MCP for conversational interaction via Claude.

---

## 6. Personal Rules (from context.json — enforced in code)

- Sleep: 1am–9am default. **Fri/Sat/Sun: nothing before noon, no exceptions.**
- Morning buffer: 90min after wake. First task never before 10:30am on weekdays.
- Late night detection: GCal event ends after 11pm → shift next day's effective wake time forward, push buffer accordingly.
- Flamingo (`colorId "4"`) = meetings/calls → **15min buffer before AND after.**
- Banana (`colorId "5"`) = events → **30min buffer before AND after.**
- Verify actual `colorId` values on first run by printing event `colorId`s via `--check`.
- Meetings/calls/events: **IMMOVABLE.** Todoist task blocks always move around them.
- No tasks after 11pm. Minimum 5min gap between any two task blocks.
- Tasks pushed 3+ times: flag prominently as at-risk.
- `@waiting` tasks are never auto-scheduled under any circumstances.

**Daily fixed blocks (from context.json daily_blocks):**
Treated identically to calendar event buffers in
compute_free_windows(). Read from context.json at startup.
Applied every day regardless of GCal content.
Movable: false means they are never scheduled over.
User can override individual instances verbally before
a --plan-day run ("lunch is at 2pm today").

---

## 7. LLM Scheduling Philosophy

Work block types and preferred time windows are **NOT hardcoded**. The LLM reasons from first principles every time using:

- `productivity_science.json` — pre-compiled research on circadian rhythm, energy levels, focus windows, task sequencing, and cognitive load theory (loaded at startup, never re-fetched)
- The user's specific free windows for that day
- Task labels, priorities, deadlines, and estimated durations
- Momentum sequencing — ordering tasks within a block to build energy and flow

After several weeks of usage data, learned patterns from `task_history` may be introduced. Until then, the LLM reasons with full autonomy within hard constraints enforced by code.

---

## 8. LLM Chain — Two-Step Pipeline

No LangChain. No framework. Two separate Groq API calls in `src/llm.py`.

### Step 1 — Enrich (`enrich_tasks`)

- **Input:** raw task list + label vocab + context rules
- **Job:** for each task, assess cognitive load, energy requirement, suggested block type, and scheduling flags
- **Output per task:**

```json
{
	"task_id": "string",
	"cognitive_load": "high | medium | low",
	"energy_requirement": "peak | moderate | low",
	"suggested_block": "descriptive string e.g. morning peak focus",
	"can_be_split": true,
	"scheduling_flags": ["string"]
}
```

### Step 2 — Schedule (`generate_schedule`)

- **Input:** enriched tasks + pre-computed free windows + date + context + `productivity_science.json` heuristics summary
- **Job:** assign tasks to time slots using productivity science reasoning. Explain briefly why each task was placed where it was. Sequence tasks within blocks for momentum.
- **Output:**

```json
{
	"reasoning_summary": "Brief note on overall approach for today",
	"scheduled": [
		{
			"task_id": "string",
			"task_name": "string",
			"start_time": "2026-04-03T09:30:00",
			"end_time": "2026-04-03T11:00:00",
			"duration_minutes": 90,
			"block_label": "string",
			"placement_reason": "string"
		}
	],
	"pushed": [
		{
			"task_id": "string",
			"task_name": "string",
			"reason": "string",
			"suggested_date": "2026-04-04"
		}
	],
	"flagged": [
		{
			"task_id": "string",
			"task_name": "string",
			"issue": "string"
		}
	]
}
```

---

## 9. productivity_science.json — Pre-Compiled Research

This file lives at the project root and is **loaded once at startup**. It is **never re-fetched or regenerated at runtime**. It contains distilled research across four domains:

- **Circadian rhythm:** alertness peaks (~10am, ~6pm), post-lunch dip (1–3pm), cognitive performance curves by time of day
- **Cognitive load theory:** high-load tasks require peak windows, switching cost between task types, batch vs interleaved scheduling
- **Deep work theory (Cal Newport):** minimum viable session lengths, context-switching penalties, protection of uninterrupted blocks
- **Task momentum:** sequencing from smaller to larger to build flow, avoiding cold-start on hardest tasks, transition buffer value

The LLM receives a structured excerpt from this file in every scheduling prompt. It uses it as a reference to justify placement decisions. This means even a smaller/cheaper model has explicit research scaffolding to reason from — it doesn't need to have memorized the research, it reads it fresh each call.

For Step 1 (enrichment): inject the full file.
For Step 2 (scheduling): inject only the `scheduling_heuristics_summary` section to keep token count lean.

---

## 10. SQLite Schema

### `task_history` — collected from day one, queried in Phase 7

```
id, task_id, task_name, project_id,
estimated_duration_mins, actual_duration_mins,
scheduled_at, completed_at, day_of_week,
was_rescheduled, reschedule_count,
was_late_night_prior, cognitive_load_label,
created_at
```

### `schedule_log` — audit trail of every run

```
id, run_at, schedule_date, proposed_json,
confirmed (bool), confirmed_at, diff_json
```

---

## 11. Todoist API Reference

**All reads and writes use REST API v1 base URL:** `https://api.todoist.com/api/v1/`

- Reads: `GET /api/v1/tasks?filter=<string>` (paginated — use `_get_all_pages()`)
- Writes: `POST /api/v1/tasks/{id}` with partial JSON body for individual task updates
- Comments: `POST /api/v1/comments`
- Activity: `GET https://api.todoist.com/sync/v9/activity/get`
- Reminders: `POST /api/v1/reminders` (Pro only)

**Due datetime:** Pass as `"due_datetime": "<ISO 8601 with tz offset>"` — e.g. `"2026-04-07T13:00:00-07:00"`. Use `datetime.isoformat()` on a tz-aware datetime object.

**Duration:** `"duration": <int>` + `"duration_unit": "minute"` — both required.

**Deadline:** `"deadline": {"date": "YYYY-MM-DD"}` — separate field from `due`.

**DEPRECATED — do not use:**

- ~~`https://api.todoist.com/rest/v2/`~~ — 410 Gone
- ~~`https://api.todoist.com/sync/v9/sync`~~ — 410 Gone (see LEARNINGS.md)

### Google Calendar colorId Reference

Verify real values on first run by printing `colorId` + `summary` for all events via `--check`:

- `"4"` = Flamingo — meetings/calls (30min buffer each side)
- `"5"` = Banana — events (30min buffer each side)

---

## 12. Current Build Phase

> **Phase 2: Write-back + date targeting.**

- Write-back to Todoist is implemented (individual REST v1 POST calls)
- `--plan-day` accepts optional date argument (today/tomorrow/monday/YYYY-MM-DD)
- DO NOT implement webhooks yet
- DO NOT implement reminders yet

---

## 13. Error Handling Conventions

- API errors: log clearly, don't crash, return empty list and warn
- LLM JSON errors: retry once, then raise with full prompt logged
- Missing `.env` vars: fail fast on startup with clear message
- Datetimes: compute in local timezone, convert to ISO 8601 for APIs
- Empty Todoist response: check HTTP status code before parsing body — distinguish auth error from genuinely empty task list

---

## 14. Testing

`src/scheduler.py` must have unit tests in `tests/test_scheduler.py`. Pure logic, no API calls, mock data only.

Minimum 5 test cases:

1. Normal weekday — standard morning buffer + work blocks
2. Late night adjustment — event ends after 11pm, next day shifts
3. Weekend noon rule — Fri/Sat/Sun, nothing before 12pm
4. Flamingo buffer collision — 30min before/after applied correctly
5. Overlapping events edge case — two events close together, buffer overlap handled

```bash
python3 -m pytest tests/
```

---

## 15. Living Learnings Log

Claude Code must maintain a file called `LEARNINGS.md` at the project root.
After every session, before finishing, append any of the following:

- API behaviour that differed from documentation
- Bugs found and how they were fixed
- Decisions made and why (e.g. model choice, data structure change)
- Anything that took more than one attempt to get right
- Deprecations, version changes, or unexpected responses from any API

Format each entry as:

### [Date] — [Short title]

[What was learned and why it matters for future sessions]

Claude Code reads LEARNINGS.md at the start of every session before writing any code.

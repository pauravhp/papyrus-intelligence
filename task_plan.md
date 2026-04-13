## Task 0 — DB migration + credential save ✅

- [x] Add `supabase/migrations/002_anthropic_key.sql` (anthropic_api_key column + set_encryption_key RPC)
- [x] Extend `PromoteRequest` with groq_api_key, anthropic_api_key, todoist_api_key
- [x] Update `onboard_promote` to call `set_encryption_key()` and save encrypted API keys
- [x] Update `Stage0.tsx` to capture anthropic_api_key
- [x] Update `Stage3.tsx` (promote call) to pass all 3 keys
- [x] Tests passing: `tests/api/test_onboard_promote.py`


## Task 1 — GCal write capability ✅

- [x] Add `build_gcal_service_from_credentials()` to `src/calendar_client.py` — returns (service, refreshed_dict | None)
- [x] Add `create_event()` to `src/calendar_client.py`
- [x] Add `delete_event()` to `src/calendar_client.py` — silently ignores 404
- [x] Add `WRITE_SCOPES` constant to `src/calendar_client.py`
- [x] Update OAuth scope in `api/routes/google_auth.py` → `calendar.events`
- [x] Update `onboard.py` stage1 to use `WRITE_SCOPES`
- [x] Tests: `tests/core/test_calendar_write.py`
- [x] All 77 tests passing


## Task 2 — schedule_day() service ✅

- [x] Add `anthropic>=0.40.0` to `requirements-api.txt`
- [x] Create `api/services/__init__.py`
- [x] Create `api/services/schedule_service.py` — Anthropic primary (claude-haiku-4-5-20251001), Groq fallback (llama-4-scout)
- [x] `_build_prompt()` — formats tasks, free windows, hard/soft rules
- [x] `_extract_json()` — strips markdown fences, finds first `{`
- [x] `_parse_with_retry()` — retries once, raises RuntimeError on double failure
- [x] Output: `{scheduled, pushed, reasoning_summary}` with JSON retry logic
- [x] Tests: `tests/api/test_schedule_service.py`
- [x] 80 tests passing


## Task 3 — Agent tool definitions ✅

- [x] Create `api/services/agent_tools.py`
- [x] 9 `execute_*` functions: get_tasks, get_calendar, schedule_day, confirm_schedule, push_task, get_status, onboard_scan, onboard_apply, onboard_confirm
- [x] `TOOL_SCHEMAS` — 9 Anthropic tool schema dicts
- [x] `TOOL_DISPATCH` — name→lambda router for the ReAct loop
- [x] Tests: `tests/api/test_agent_tools.py`
- [x] 86 tests passing


## Task 4 — Chat endpoint

- [ ] Create `api/routes/chat.py` (ReAct loop, max 10 iterations, stateless history)
- [ ] System prompt, BYOK key loading from Supabase, GCal service init
- [ ] Register in `api/main.py`
- [ ] Tests: `tests/api/test_chat.py`


## Task 5 — Chat UI

- [ ] Replace `frontend/app/dashboard/page.tsx` stub
- [ ] Create `frontend/app/dashboard/ChatWindow.tsx`
- [ ] Create `frontend/app/dashboard/ScheduleCard.tsx`
- [ ] Create `frontend/app/dashboard/ConfirmButtons.tsx`
- [ ] Smoke test: message → ScheduleCard → confirm → GCal event appears

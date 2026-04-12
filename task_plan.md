## Step 1 — GCal write capability

- [ ] Add `create_event()` to `src/calendar_client.py`
- [ ] Add `delete_event()` to `src/calendar_client.py`
- [ ] Add `build_gcal_service_from_credentials()` to `src/calendar_client.py`
- [ ] Update OAuth scope in `api/routes/google_auth.py`
- [ ] Add `todoist_tier: "free"` to `context.template.json`
- [ ] Write tests for create/delete event  


## Step 2 — schedule_day() service

- [ ] Create `api/services/schedule_service.py`
- [ ] Single LLM call replacing 4-step pipeline
- [ ] Accepts context_note parameter
- [ ] Output validation (sleep hours, duration bounds)
- [ ] Write tests  


## Step 3 — Agent tool definitions

- [ ] Create `api/services/agent_tools.py`
- [ ] Define all 9 tools (get_tasks, get_calendar, schedule_day, confirm_schedule, push_task, get_status, onboard_scan, onboard_apply, onboard_confirm)
- [ ] Write tests for each tool's Python implementation  


## Step 4 — Chat endpoint

- [ ] Create `api/routes/chat.py`
- [ ] Agent loop with tool execution
- [ ] System prompt
- [ ] BYOK (Anthropic + Groq fallback)
- [ ] Register in `api/main.py`
- [ ] Integration test: plan → confirm flow  


## Step 5 — Chat UI

- [ ] Replace `frontend/app/dashboard/page.tsx` stub
- [ ] `ChatWindow.tsx` component
- [ ] `ScheduleCard.tsx` component
- [ ] `ConfirmButtons.tsx` component
- [ ] End-to-end test: message → schedule renders → confirm → GCal events appear

"""
Migration parser — single Haiku call that converts raw user task dumps
into structured Papyrus inputs (tasks + rhythms + unmatched).

Mirrors the shape of api/services/extractor.py and api/services/schedule_service.py:
- Single LLM call, JSON-only output
- System prompt cached (cache_control: ephemeral)
- Retry once on JSON parse failure; raise MigrationParseError on second failure

Hard constraints (duration snapping, deadline clamping, dedupe) live in
api.services.migration_validator — this module just orchestrates the
LLM call and delegates normalisation.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date

import anthropic

from api.services.migration_validator import normalise_proposal

logger = logging.getLogger(__name__)

PARSER_MODEL = "claude-haiku-4-5-20251001"

# Maximum input length enforced server-side before we even spend a token.
# MIN floor is intentionally low (1) — the user-facing minimum (e.g. 20 chars)
# is enforced at the route layer so unit tests can use short stub strings.
MAX_INPUT_CHARS = 5_000
MIN_INPUT_CHARS = 1

# v1 system prompt. Iteration happens in Task 5 once we have real fixtures
# — but the structure here is the contract:
#   - JSON-only output, exact shape
#   - Constrained category enum
#   - Blessed duration set
#   - Source-format awareness (Notion, MS ToDo, Apple Notes, Notion-AI,
#     brain dump)
#   - Preserve user's language
#   - Don't multiply (one rhythm with multiple days, not multiple tasks)
PARSER_SYSTEM_PROMPT = """You convert a user's raw task dump into structured Papyrus inputs.

OUTPUT — JSON only, no commentary, no markdown fences, this exact shape:
{
  "tasks": [
    {
      "content": "<task name, cleaned up, in user's language>",
      "priority": 1-4,
      "duration_minutes": <one of: 10, 15, 30, 45, 60, 75, 90, 120, 180>,
      "category_label": "@deep-work" | "@admin" | "@quick" | null,
      "deadline": "YYYY-MM-DD" | null,
      "reasoning": "<one short sentence why you chose these values>"
    }
  ],
  "rhythms": [
    {
      "name": "<descriptive name, in user's language>",
      "scheduling_hint": "<short natural-language placement hint>",
      "sessions_per_week": <int 1-21>,
      "session_min_minutes": <one of the blessed durations>,
      "session_max_minutes": <one of the blessed durations, >= min>,
      "days_of_week": ["mon"|"tue"|"wed"|"thu"|"fri"|"sat"|"sun", ...],
      "reasoning": "<one short sentence why this is a rhythm not a task>"
    }
  ],
  "unmatched": ["<original line>", ...]
}

CLASSIFICATION:
- A line is a RHYTHM if it implies recurrence: "every Monday", "weekly",
  "M/W/F", "daily", "morning routine", "verbing every <day>".
- Otherwise it is a TASK.
- Lines you can't classify confidently go in `unmatched` verbatim.

DON'T MULTIPLY:
- "Mon: gym, Tue: gym, Wed: gym" is ONE rhythm with days_of_week=["mon","tue","wed"].
- "Email Sarah" appearing twice → ONE task.

DURATION INFERENCE — choose the nearest blessed duration:
- emails / quick replies / pings → 15
- meetings/calls (no explicit duration) → 30
- "write" / "draft" / "design" / "build" / "research" → 60 or 90
- "review" / "read through" / "go over" → 30
- if unsure → 30

CATEGORY INFERENCE:
- @deep-work: writing, designing, building, focused thinking, code
- @admin: emails, replies, scheduling, paperwork, coordination
- @quick: anything inferred at 15 min and not deep work
- null: leave unset for ambiguous cases

PRIORITY INFERENCE:
- explicit "URGENT", "ASAP", "today" → 4 (P1)
- explicit deadlines within 7 days → 3 (P2)
- "someday" / "maybe" / "would be nice" → 2 or 1
- default → 3 (P2)

DEADLINE INFERENCE:
- Parse phrases like "by Friday", "due next Tue", "before end of week"
  into ISO dates relative to TODAY (provided in the user message).
- Otherwise null.

SOURCE FORMATS — handle these cleanly:
- Notion checkbox export: lines like "- [ ] Task name" — strip prefix.
- Notion-AI structured export: lines like "Task: <name>, Priority: high, Due: Friday" — parse columns.
- MS ToDo export: lines like "( ) Item" or "[ ] Item" — strip prefix.
- Apple Notes / Google Keep: bulleted lists, no metadata.
- Free-form brain dump: paragraphs separated by commas/newlines.

PRESERVE LANGUAGE: if the dump isn't English, keep `content` and `name` in
that language. Only `category_label` values stay English.

Respond with ONLY the JSON object."""


class MigrationParseError(RuntimeError):
    """Raised when the LLM returns invalid JSON twice in a row."""


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    if "```" in text:
        text = re.sub(r"^```(?:json)?\s*\n?", "", text, flags=re.MULTILINE)
        text = re.sub(r"\n?```\s*$", "", text)
        text = text.strip()
    if text and text[0] not in "{[":
        for i, ch in enumerate(text):
            if ch in "{[":
                text = text[i:]
                break
    return text.strip()


def _build_user_message(raw_text: str, today: date) -> str:
    return f"""TODAY: {today.isoformat()} ({today.strftime('%A')})

USER DUMP:
{raw_text}"""


def parse_migration_dump(
    *,
    raw_text: str,
    today: date,
    anthropic_api_key: str | None,
) -> dict:
    """Run the parser. Returns a normalised proposal dict.

    Raises:
        MigrationParseError: LLM returned malformed JSON twice, OR the
            server is misconfigured (missing anthropic_api_key).
        ValueError: input failed length checks (caller maps to 400).
    """
    text = (raw_text or "").strip()
    if len(text) < MIN_INPUT_CHARS:
        raise ValueError("input_too_short")
    if len(text) > MAX_INPUT_CHARS:
        raise ValueError("input_too_long")
    if not anthropic_api_key:
        raise MigrationParseError("anthropic key missing")

    client = anthropic.Anthropic(api_key=anthropic_api_key)
    user_message = _build_user_message(text, today)

    last_raw = ""
    for attempt in (1, 2):
        try:
            resp = client.messages.create(
                model=PARSER_MODEL,
                max_tokens=8192,
                temperature=0.2,
                system=[
                    {
                        "type": "text",
                        "text": PARSER_SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": user_message}],
            )
            last_raw = resp.content[0].text if resp.content else ""
            data = json.loads(_strip_json_fences(last_raw))
        except json.JSONDecodeError:
            logger.warning(
                "[migration_parser] attempt %d JSON parse failed; raw=%s",
                attempt, last_raw[:500],
            )
            if attempt == 2:
                logger.error(
                    "[migration_parser] both attempts failed; full raw=%s",
                    last_raw,
                )
                raise MigrationParseError("LLM returned malformed JSON twice")
            continue
        return normalise_proposal(data, today=today)

    raise MigrationParseError("unreachable")

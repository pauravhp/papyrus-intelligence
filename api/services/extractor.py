"""
Constraint extraction LLM call.

Given a user's natural-language scheduling note (plus carry-forward state from
prior turns), returns structured time-blocks and an optional end-of-day cutoff
override. The scheduler LLM never sees prose constraints — by the time it runs,
this module has already turned them into deterministic data the windows math
can use.

This split is the architectural answer to the "LLM declared a block but
scheduled into it anyway" failure mode we kept hitting on 2026-04-25. With one
call per concern and Python in between, constraint adherence is no longer a
matter of model self-discipline.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import anthropic

logger = logging.getLogger(__name__)

EXTRACTOR_MODEL = "claude-haiku-4-5-20251001"

EXTRACTOR_SYSTEM_PROMPT = """You extract structured time constraints from a user's natural-language scheduling notes.

INPUT (in the user message):
- TARGET_DATE: the calendar date being planned (YYYY-MM-DD)
- TIMEZONE: the user's UTC offset, e.g. "-07:00"
- ACTIVE BLOCKS: time-block constraints already known from earlier turns (may be empty)
- ACTIVE CUTOFF: an end-of-day cutoff already stated (or null)
- USER PROSE: this turn's free-form note

OUTPUT (only this JSON shape, nothing else, no markdown fences):
{"blocks":[{"start_iso":"","end_iso":"","source":""}],"cutoff_override_iso":""}

If cutoff is not set or stays null, use null literally:
{"blocks":[],"cutoff_override_iso":null}

DATETIME RULES:
- All datetimes are full ISO 8601 with the supplied TIMEZONE offset, NOT UTC.
  CORRECT:   "2026-04-25T22:00:00-07:00"
  WRONG:     "22:00"  (no date, no offset)
- Cross-midnight blocks: end_iso uses the NEXT day's date.
  "10pm to 12:30am" with TARGET_DATE=2026-04-25, TIMEZONE=-07:00 →
    start_iso="2026-04-25T22:00:00-07:00", end_iso="2026-04-26T00:30:00-07:00"
- Cutoffs that extend past midnight use the NEXT day's date.
  "I can work until 3:30am tonight" with TARGET_DATE=2026-04-25 →
    cutoff_override_iso="2026-04-26T03:30:00-07:00"

WHAT IS A BLOCK vs A CUTOFF:
- BLOCK = a specific time range when the user is unavailable for tasks.
  "I have an event 4-9pm" → block 16:00–21:00
  "in class till noon" → block 00:00–12:00
  "blocked 14:00-15:30" → block 14:00–15:30
  "free after 6pm" → block 00:00–18:00 (unavailable BEFORE 6pm)
- CUTOFF = the latest time the user can do tasks today (end-of-day).
  "I can work until 3am" → cutoff 03:00 next day
  "wrap by 8pm" → cutoff 20:00
  "stop at 22:00" → cutoff 22:00
  "free until 3pm" → cutoff 15:00 (available BEFORE 3pm; nothing usable after)

CARRY-FORWARD (PERSIST UNLESS REMOVED):
- ACTIVE BLOCKS persist by default — include them in your output unless the prose explicitly removes one.
  - "ignore the earlier event" / "I no longer have that event" / "drop the block" → REMOVE the matching block
  - "extend it 30 min" / "actually it's 4-10pm now" → MODIFY the matching block
  - Prose silent on a block → KEEP it as-is
- ACTIVE CUTOFF persists similarly. A new cutoff in prose overrides; silence keeps; "use my normal cutoff" / "go back to default" removes (return null).

NO HALLUCINATION:
- If the prose does NOT mention any time constraint, return ACTIVE BLOCKS and ACTIVE CUTOFF UNCHANGED.
- Do NOT invent constraints from vague phrases ("busy day", "tight schedule", "lots to do").
- Only emit a constraint when the user named a specific time."""


# ── Public types ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Block:
    """A user-stated unavailable time range."""
    start_iso: str  # full ISO 8601 with offset
    end_iso: str
    source: str

    def to_dict(self) -> dict:
        return {"start_iso": self.start_iso, "end_iso": self.end_iso, "source": self.source}

    @classmethod
    def from_dict(cls, d: dict) -> Block | None:
        try:
            start = str(d["start_iso"])
            end = str(d["end_iso"])
            datetime.fromisoformat(start)  # validate
            end_dt = datetime.fromisoformat(end)
            start_dt = datetime.fromisoformat(start)
            if end_dt <= start_dt:
                return None
            return cls(start_iso=start, end_iso=end, source=str(d.get("source", "")))
        except (KeyError, ValueError, TypeError):
            return None


@dataclass(frozen=True)
class ExtractionResult:
    blocks: list[Block]
    cutoff_override_iso: str | None  # full ISO datetime or None

    def to_dict(self) -> dict:
        return {
            "blocks": [b.to_dict() for b in self.blocks],
            "cutoff_override_iso": self.cutoff_override_iso,
        }


EMPTY_RESULT = ExtractionResult(blocks=[], cutoff_override_iso=None)


# ── Internals ─────────────────────────────────────────────────────────────────


def _format_active_blocks(blocks: list[Block]) -> str:
    if not blocks:
        return "NONE"
    return "\n".join(
        f"- {b.start_iso} → {b.end_iso}: {b.source}"
        for b in blocks
    )


def _build_user_message(
    target_date_str: str,
    tz_offset: str,
    active_blocks: list[Block],
    active_cutoff_iso: str | None,
    prose: str,
) -> str:
    return f"""TARGET_DATE: {target_date_str}
TIMEZONE: {tz_offset}

ACTIVE BLOCKS:
{_format_active_blocks(active_blocks)}

ACTIVE CUTOFF: {active_cutoff_iso if active_cutoff_iso else "null"}

USER PROSE:
{prose or "(empty)"}"""


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


def _parse_extraction(raw: str) -> ExtractionResult:
    """Parse the LLM's JSON output. Falls back to EMPTY on malformed input."""
    try:
        data: Any = json.loads(_strip_json_fences(raw))
    except json.JSONDecodeError as exc:
        logger.warning("[extractor] JSON parse failed: %s\nraw: %s", exc, raw[:500])
        return EMPTY_RESULT

    if not isinstance(data, dict):
        logger.warning("[extractor] response not an object: %r", type(data))
        return EMPTY_RESULT

    blocks: list[Block] = []
    for raw_block in data.get("blocks") or []:
        if not isinstance(raw_block, dict):
            continue
        b = Block.from_dict(raw_block)
        if b is not None:
            blocks.append(b)

    cutoff_raw = data.get("cutoff_override_iso")
    cutoff: str | None = None
    if cutoff_raw and cutoff_raw != "null":
        try:
            datetime.fromisoformat(str(cutoff_raw))
            cutoff = str(cutoff_raw)
        except ValueError:
            logger.warning("[extractor] cutoff_override_iso not a valid ISO: %r", cutoff_raw)

    return ExtractionResult(blocks=blocks, cutoff_override_iso=cutoff)


# ── Public API ────────────────────────────────────────────────────────────────


def extract_constraints(
    *,
    prose: str,
    target_date_str: str,
    tz_offset: str,
    previous_blocks: list[Block] | None = None,
    previous_cutoff_iso: str | None = None,
    anthropic_api_key: str | None,
) -> ExtractionResult:
    """
    Extract time-block and cutoff constraints from prose.

    The LLM is given the active state from previous turns and decides what to
    keep, modify, or remove based on the new prose. Default-keep semantics —
    silence on a constraint preserves it.

    Returns EMPTY on missing API key or unparseable response — graceful
    degradation; the scheduling pipeline can still run, it just won't honor
    new prose constraints from this turn (carry-forward from previous still
    works because the caller passes those state directly into windows).
    """
    if not anthropic_api_key:
        logger.warning("[extractor] no anthropic key; returning carry-forward only")
        return ExtractionResult(
            blocks=list(previous_blocks or []),
            cutoff_override_iso=previous_cutoff_iso,
        )

    user_message = _build_user_message(
        target_date_str=target_date_str,
        tz_offset=tz_offset,
        active_blocks=list(previous_blocks or []),
        active_cutoff_iso=previous_cutoff_iso,
        prose=prose or "",
    )

    client = anthropic.Anthropic(api_key=anthropic_api_key)

    try:
        resp = client.messages.create(
            model=EXTRACTOR_MODEL,
            max_tokens=1024,
            temperature=0.0,
            system=[
                {
                    "type": "text",
                    "text": EXTRACTOR_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as exc:
        logger.warning("[extractor] LLM call failed: %s — falling back to carry-forward", exc)
        return ExtractionResult(
            blocks=list(previous_blocks or []),
            cutoff_override_iso=previous_cutoff_iso,
        )

    raw = resp.content[0].text if resp.content else ""
    print(f"[extractor] user message:\n{user_message}")
    print(f"[extractor] raw response:\n{raw}")
    parsed = _parse_extraction(raw)
    print(
        f"[extractor] parsed: {len(parsed.blocks)} block(s), "
        f"cutoff_override_iso={parsed.cutoff_override_iso}"
    )
    for b in parsed.blocks:
        print(f"  block: {b.start_iso} → {b.end_iso} | source={b.source!r}")
    return parsed

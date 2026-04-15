"""
LLM helpers — Anthropic JSON calls used by onboard and plan routes.

JSON validation: retry once on parse failure; log full prompt on second failure.
"""

import json
import re

import anthropic

ANTHROPIC_SCHEDULE_MODEL = "claude-haiku-4-5-20251001"


# ── JSON helpers ───────────────────────────────────────────────────────────────


def _extract_json(text: str) -> str:
    """Strip markdown fences and any preamble text, leaving raw JSON."""
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


def _anthropic_json_call(
    client,  # anthropic.Anthropic instance
    messages: list[dict],
    description: str,
    system: str = "",
) -> dict | list:
    """
    Call Anthropic expecting a JSON response. Retries once on parse failure.
    Logs full prompt + raw response if both attempts fail, then raises.
    """
    last_content: str = ""
    user_msgs = [m for m in messages if m.get("role") != "system"]
    sys_prompt = system or next(
        (m["content"] for m in messages if m.get("role") == "system"), ""
    )
    for attempt in range(1, 3):
        try:
            resp = client.messages.create(
                model=ANTHROPIC_SCHEDULE_MODEL,
                max_tokens=2048,
                system=sys_prompt,
                messages=user_msgs,
            )
            last_content = resp.content[0].text or ""
            cleaned = _extract_json(last_content)
            return json.loads(cleaned)
        except json.JSONDecodeError:
            if attempt < 2:
                print(f"[LLM] Attempt 1 JSON parse failed for '{description}' (Anthropic) — retrying…")
                continue
            print(f"\n[LLM] CRITICAL: both attempts failed for '{description}' (Anthropic)")
            print(f"[LLM] ── FULL PROMPT ──\n{json.dumps(messages, indent=2)}")
            print(f"[LLM] ── RAW RESPONSE ──\n{last_content}")
            raise RuntimeError(
                f"LLM returned invalid JSON for '{description}' after 2 attempts"
            )
    raise RuntimeError("Unexpected exit from _anthropic_json_call")

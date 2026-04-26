"""
Tests for api.services.extractor — the constraint-extraction LLM call.

The extractor is the first half of the new two-call pipeline. It takes prose
plus carry-forward state and returns structured blocks + cutoff_override.
The scheduling LLM never sees prose constraints — by the time it runs, this
service has already turned them into deterministic data.
"""

import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "test-secret")
os.environ.setdefault("ENCRYPTION_KEY", "test-enc-key-32-chars-padding!!")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-gcal-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-gcal-secret")
os.environ.setdefault("TODOIST_CLIENT_ID", "test-td-id")
os.environ.setdefault("TODOIST_CLIENT_SECRET", "test-td-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")

from unittest.mock import MagicMock, patch

from api.services.extractor import (
    Block,
    ExtractionResult,
    extract_constraints,
    _build_user_message,
    _parse_extraction,
)


# ── Block parsing ─────────────────────────────────────────────────────────────


def test_block_from_dict_accepts_valid():
    b = Block.from_dict({
        "start_iso": "2026-04-25T22:00:00-07:00",
        "end_iso":   "2026-04-26T00:30:00-07:00",
        "source": "event 10pm-12:30am",
    })
    assert b is not None
    assert b.source == "event 10pm-12:30am"


def test_block_from_dict_rejects_zero_or_negative_range():
    assert Block.from_dict({"start_iso": "2026-04-25T10:00:00-07:00",
                             "end_iso":   "2026-04-25T10:00:00-07:00"}) is None
    assert Block.from_dict({"start_iso": "2026-04-25T10:00:00-07:00",
                             "end_iso":   "2026-04-25T09:00:00-07:00"}) is None


def test_block_from_dict_rejects_malformed():
    assert Block.from_dict({"start_iso": "not-a-date", "end_iso": "also-not"}) is None
    assert Block.from_dict({"start_iso": "2026-04-25T10:00:00-07:00"}) is None  # missing end


# ── Response parsing ──────────────────────────────────────────────────────────


def test_parse_extraction_handles_clean_json():
    raw = '{"blocks":[{"start_iso":"2026-04-25T16:00:00-07:00","end_iso":"2026-04-25T21:00:00-07:00","source":"event 4-9pm"}],"cutoff_override_iso":null}'
    result = _parse_extraction(raw)
    assert len(result.blocks) == 1
    assert result.blocks[0].source == "event 4-9pm"
    assert result.cutoff_override_iso is None


def test_parse_extraction_handles_fenced_json():
    raw = '```json\n{"blocks":[],"cutoff_override_iso":"2026-04-26T03:30:00-07:00"}\n```'
    result = _parse_extraction(raw)
    assert result.blocks == []
    assert result.cutoff_override_iso == "2026-04-26T03:30:00-07:00"


def test_parse_extraction_returns_empty_on_garbage():
    assert _parse_extraction("not json at all") == ExtractionResult(blocks=[], cutoff_override_iso=None)
    assert _parse_extraction("") == ExtractionResult(blocks=[], cutoff_override_iso=None)


def test_parse_extraction_drops_invalid_blocks_keeps_valid():
    raw = '{"blocks":[{"start_iso":"bad","end_iso":"also bad"},{"start_iso":"2026-04-25T16:00:00-07:00","end_iso":"2026-04-25T21:00:00-07:00","source":"ok"}],"cutoff_override_iso":null}'
    result = _parse_extraction(raw)
    assert len(result.blocks) == 1
    assert result.blocks[0].source == "ok"


def test_parse_extraction_drops_invalid_cutoff():
    raw = '{"blocks":[],"cutoff_override_iso":"not-a-datetime"}'
    result = _parse_extraction(raw)
    assert result.cutoff_override_iso is None


# ── User message construction ─────────────────────────────────────────────────


def test_user_message_includes_active_state_and_prose():
    prior_block = Block(
        start_iso="2026-04-25T22:00:00-07:00",
        end_iso="2026-04-26T00:30:00-07:00",
        source="event 10pm-12:30am",
    )
    msg = _build_user_message(
        target_date_str="2026-04-25",
        tz_offset="-07:00",
        active_blocks=[prior_block],
        active_cutoff_iso=None,
        prose="actually I want to do Todoist Scheduler for the entirety of today",
    )
    assert "TARGET_DATE: 2026-04-25" in msg
    assert "TIMEZONE: -07:00" in msg
    assert "2026-04-25T22:00:00-07:00 → 2026-04-26T00:30:00-07:00: event 10pm-12:30am" in msg
    assert "ACTIVE CUTOFF: null" in msg
    assert "Todoist Scheduler" in msg


def test_user_message_with_no_active_state():
    msg = _build_user_message(
        target_date_str="2026-04-25",
        tz_offset="-07:00",
        active_blocks=[],
        active_cutoff_iso=None,
        prose="",
    )
    assert "ACTIVE BLOCKS:\nNONE" in msg
    assert "ACTIVE CUTOFF: null" in msg
    assert "USER PROSE:\n(empty)" in msg


# ── End-to-end (mocked LLM) ───────────────────────────────────────────────────


def test_extract_passes_carry_forward_in_user_message():
    """Verify the LLM call receives the right user message structure."""
    captured = {}

    fake_resp = MagicMock()
    fake_resp.content = [MagicMock(text='{"blocks":[],"cutoff_override_iso":null}')]

    fake_messages = MagicMock()
    fake_messages.create.return_value = fake_resp

    prior_block = Block(
        start_iso="2026-04-25T22:00:00-07:00",
        end_iso="2026-04-26T00:30:00-07:00",
        source="event 10pm-12:30am",
    )

    with patch("api.services.extractor.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages = fake_messages
        result = extract_constraints(
            prose="extend the event by 30 min",
            target_date_str="2026-04-25",
            tz_offset="-07:00",
            previous_blocks=[prior_block],
            previous_cutoff_iso=None,
            anthropic_api_key="sk-test",
        )

    assert isinstance(result, ExtractionResult)
    sent_msg = fake_messages.create.call_args.kwargs["messages"][0]["content"]
    assert "extend the event by 30 min" in sent_msg
    assert "event 10pm-12:30am" in sent_msg

    # System prompt is sent as a cached block
    system_arg = fake_messages.create.call_args.kwargs["system"]
    assert system_arg[0]["cache_control"] == {"type": "ephemeral"}


def test_extract_falls_back_to_carry_forward_on_no_api_key():
    """Without an API key, return the carry-forward state unchanged — graceful degradation."""
    prior_block = Block(
        start_iso="2026-04-25T22:00:00-07:00",
        end_iso="2026-04-26T00:30:00-07:00",
        source="event 10pm-12:30am",
    )
    result = extract_constraints(
        prose="anything",
        target_date_str="2026-04-25",
        tz_offset="-07:00",
        previous_blocks=[prior_block],
        previous_cutoff_iso="2026-04-26T03:30:00-07:00",
        anthropic_api_key=None,
    )
    assert result.blocks == [prior_block]
    assert result.cutoff_override_iso == "2026-04-26T03:30:00-07:00"


def test_extract_falls_back_to_carry_forward_on_llm_error():
    """If the API call raises, fall back to carry-forward instead of dropping state."""
    fake_messages = MagicMock()
    fake_messages.create.side_effect = RuntimeError("network down")

    prior_block = Block(
        start_iso="2026-04-25T22:00:00-07:00",
        end_iso="2026-04-26T00:30:00-07:00",
        source="event",
    )

    with patch("api.services.extractor.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages = fake_messages
        result = extract_constraints(
            prose="any prose",
            target_date_str="2026-04-25",
            tz_offset="-07:00",
            previous_blocks=[prior_block],
            previous_cutoff_iso=None,
            anthropic_api_key="sk-test",
        )
    assert result.blocks == [prior_block]

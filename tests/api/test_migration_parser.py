import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from api.services.migration_parser import (
    MigrationParseError,
    parse_migration_dump,
)


def _mock_anthropic_response(payload: dict | str):
    text = json.dumps(payload) if isinstance(payload, dict) else payload
    block = MagicMock()
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    return resp


def test_parse_migration_dump_happy_path():
    captured = {
        "tasks": [
            {
                "content": "Draft launch announcement",
                "priority": 3,
                "duration_minutes": 60,
                "category_label": "@deep-work",
                "deadline": "2026-05-01",
                "reasoning": "writing task with end-of-week deadline",
            }
        ],
        "rhythms": [
            {
                "name": "Morning workout",
                "scheduling_hint": "mornings only",
                "session_min_minutes": 30,
                "session_max_minutes": 60,
                "sessions_per_week": 5,
                "days_of_week": ["mon", "tue", "wed", "thu", "fri"],
                "reasoning": "explicit weekday recurrence",
            }
        ],
        "unmatched": ["maybe rebuild the porch??"],
    }
    with patch("api.services.migration_parser.anthropic.Anthropic") as MockClient:
        client = MockClient.return_value
        client.messages.create.return_value = _mock_anthropic_response(captured)
        result = parse_migration_dump(
            raw_text="Draft launch announcement",
            today=date(2026, 4, 27),
            anthropic_api_key="test-key",
        )
    assert len(result["tasks"]) == 1
    assert result["tasks"][0]["duration_minutes"] == 60
    assert len(result["rhythms"]) == 1
    assert result["unmatched"] == ["maybe rebuild the porch??"]


def test_parse_migration_dump_retries_once_on_malformed_json():
    bad_then_good = [
        _mock_anthropic_response("not json at all"),
        _mock_anthropic_response({"tasks": [], "rhythms": [], "unmatched": []}),
    ]
    with patch("api.services.migration_parser.anthropic.Anthropic") as MockClient:
        client = MockClient.return_value
        client.messages.create.side_effect = bad_then_good
        result = parse_migration_dump(
            raw_text="paste",
            today=date(2026, 4, 27),
            anthropic_api_key="test-key",
        )
    assert result == {"tasks": [], "rhythms": [], "unmatched": []}
    assert client.messages.create.call_count == 2


def test_parse_migration_dump_raises_after_two_failures():
    with patch("api.services.migration_parser.anthropic.Anthropic") as MockClient:
        client = MockClient.return_value
        client.messages.create.side_effect = [
            _mock_anthropic_response("garbage 1"),
            _mock_anthropic_response("garbage 2"),
        ]
        with pytest.raises(MigrationParseError):
            parse_migration_dump(
                raw_text="paste",
                today=date(2026, 4, 27),
                anthropic_api_key="test-key",
            )
        assert client.messages.create.call_count == 2


def test_parse_migration_dump_raises_when_api_key_missing():
    with pytest.raises(MigrationParseError):
        parse_migration_dump(
            raw_text="some valid input that's at least one char",
            today=date(2026, 4, 27),
            anthropic_api_key=None,
        )


def test_parse_migration_dump_raises_when_response_content_is_empty():
    empty_block = MagicMock()
    empty_block.content = []
    with patch("api.services.migration_parser.anthropic.Anthropic") as MockClient:
        client = MockClient.return_value
        client.messages.create.return_value = empty_block
        with pytest.raises(MigrationParseError):
            parse_migration_dump(
                raw_text="some valid input that's at least one char",
                today=date(2026, 4, 27),
                anthropic_api_key="test-key",
            )
        assert client.messages.create.call_count == 2


def test_parse_migration_dump_strips_markdown_fences():
    fenced = "```json\n" + json.dumps({"tasks": [], "rhythms": [], "unmatched": []}) + "\n```"
    with patch("api.services.migration_parser.anthropic.Anthropic") as MockClient:
        client = MockClient.return_value
        client.messages.create.return_value = _mock_anthropic_response(fenced)
        result = parse_migration_dump(
            raw_text="paste",
            today=date(2026, 4, 27),
            anthropic_api_key="test-key",
        )
    assert result == {"tasks": [], "rhythms": [], "unmatched": []}


def test_parse_migration_dump_applies_validator():
    raw = {
        "tasks": [{
            "content": "Task A",
            "priority": 99,            # out of range → 4
            "duration_minutes": 7,     # below floor → 10
            "category_label": "@made-up",  # invalid → null
            "deadline": "1999-01-01",  # past → null
            "reasoning": "",
        }],
        "rhythms": [],
        "unmatched": [],
    }
    with patch("api.services.migration_parser.anthropic.Anthropic") as MockClient:
        client = MockClient.return_value
        client.messages.create.return_value = _mock_anthropic_response(raw)
        result = parse_migration_dump(
            raw_text="paste",
            today=date(2026, 4, 27),
            anthropic_api_key="test-key",
        )
    t = result["tasks"][0]
    assert t["priority"] == 4
    assert t["duration_minutes"] == 10
    assert t["category_label"] is None
    assert t["deadline"] is None


# ── Frozen real-LLM fixtures ─────────────────────────────────────────────────

from pathlib import Path

_FIXTURES = Path(__file__).parent.parent / "fixtures" / "migration"
_FIXTURE_NAMES = [
    "notion_checkbox_export",
    "notion_ai_structured_export",
    "apple_notes_dump",
    "mstodo_export",
    "brain_dump",
]
_BLESSED_DURATIONS = {10, 15, 30, 45, 60, 75, 90, 120, 180}
_VALID_CATEGORIES = {"@deep-work", "@admin", "@quick", None}
_VALID_DAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}


@pytest.mark.parametrize("name", _FIXTURE_NAMES)
def test_fixture_roundtrip_validates(name):
    """Every captured fixture response is structurally valid post-validator."""
    response = json.loads((_FIXTURES / f"{name}_response.json").read_text())
    for t in response["tasks"]:
        assert t["duration_minutes"] in _BLESSED_DURATIONS
        assert 1 <= t["priority"] <= 4
        assert t["category_label"] in _VALID_CATEGORIES
    for r in response["rhythms"]:
        assert r["session_min_minutes"] in _BLESSED_DURATIONS
        assert r["session_max_minutes"] in _BLESSED_DURATIONS
        assert r["session_min_minutes"] <= r["session_max_minutes"]
        assert 1 <= r["sessions_per_week"] <= 21
        assert all(d in _VALID_DAYS for d in r["days_of_week"])

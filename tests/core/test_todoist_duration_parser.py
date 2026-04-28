"""Tests for the flexible Todoist duration label parser.

Background: friend's usability test (2026-04-27) showed users typing `@1h`,
`@1hr`, `@45min`, `@10min` — none of which parsed under the old rigid
DURATION_LABEL_MAP. Tasks were silently skipped from scheduling.

Parser contract (see src/todoist_client.py::parse_duration_label):
  - Accepts @<n>min, @<n>m, @<n>h, @<n>hr(s), @<n> hour(s), with decimals.
  - Rounds to nearest 5 min, clamps to [10, 240].
  - Returns None for malformed input, non-duration labels, and 0-rounded values.
  - Backwards-compatible with all entries in DURATION_LABEL_MAP.
"""
import pytest

from src.todoist_client import DURATION_LABEL_MAP, parse_duration_label


# --------------------------------------------------------------------------- #
# 1. Backwards compat: every key in DURATION_LABEL_MAP still parses identically.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "label,expected",
    list(DURATION_LABEL_MAP.items()),
)
def test_legacy_map_entries_still_parse(label: str, expected: int):
    assert parse_duration_label(label) == expected


# --------------------------------------------------------------------------- #
# 2. New flexible shapes (the user-visible improvement).
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "label,expected",
    [
        # the canonical equivalence the brief calls out: @1h ≡ @60min
        ("1h", 60),
        ("1hr", 60),
        ("1hrs", 60),
        ("1 hour", 60),
        ("1 hours", 60),
        # explicit short forms
        ("60m", 60),
        ("60 min", 60),
        ("90m", 90),
        ("2hr", 120),
        ("2hrs", 120),
        ("2 hour", 120),
        ("2 hours", 120),
        # decimals
        ("1.5h", 90),
        ("0.5h", 30),
        ("2.5h", 150),
        ("0.25h", 15),
        # explicit @10/45/75 min — friend's first frustration was @10min missing
        ("10min", 10),
        ("45min", 45),
        ("75min", 75),
        # case-insensitivity
        ("60MIN", 60),
        ("1H", 60),
        ("1Hr", 60),
        ("60Min", 60),
    ],
)
def test_flexible_shapes(label: str, expected: int):
    assert parse_duration_label(label) == expected


# --------------------------------------------------------------------------- #
# 3. Rounding to nearest 5 and clamping bounds.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "label,expected",
    [
        ("12min", 10),  # 12 → 10 (rounds to 10, then clamped up to floor)
        ("13min", 15),
        ("17min", 15),
        ("18min", 20),
        ("22min", 20),
        ("23min", 25),
        # below floor → clamped to 10
        ("3min", 10),
        ("5min", 10),
        ("9min", 10),
        # above ceiling → clamped to 240
        ("5h", 240),
        ("9999h", 240),
        ("241min", 240),
        ("4hr", 240),
        # decimals that fall between 5-min steps
        ("0.4h", 25),  # 24 → 25
        ("1.1h", 65),
    ],
)
def test_rounding_and_clamping(label: str, expected: int):
    assert parse_duration_label(label) == expected


# --------------------------------------------------------------------------- #
# 4. Malformed / non-duration labels return None silently.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "label",
    [
        "",
        "deep-work",
        "admin",
        "abc",
        "min",          # number missing
        "h",
        "0min",         # zero rejected (rounds to 0)
        "0.0h",
        "0h",
        "1.5",          # unit missing
        "60",           # unit missing
        "1minute",      # unit not in accepted aliases ("hour" is, "minute" is not)
        "30min-extra",  # trailing text disallowed (anchored)
        "extra-30min",
        "1d",           # days not supported
        "1.5.0h",       # malformed decimal
        "@30min",       # leading @ stripped before this fn is called
    ],
)
def test_malformed_returns_none(label: str):
    assert parse_duration_label(label) is None


# --------------------------------------------------------------------------- #
# 5. End-to-end: _parse_task picks up the new shapes.
# --------------------------------------------------------------------------- #


def _make_client():
    from src.todoist_client import TodoistClient
    return TodoistClient(api_token="dummy")


def _raw_task(labels: list[str]) -> dict:
    return {
        "id": "t1",
        "content": "do the thing",
        "project_id": "p1",
        "priority": 1,
        "labels": labels,
    }


def test_parse_task_picks_up_at_1h_as_60_minutes():
    client = _make_client()
    parsed = client._parse_task(_raw_task(["1h", "deep-work"]), inbox_project_id="p1")
    assert parsed.duration_minutes == 60
    assert parsed.labels == ["deep-work"]


def test_parse_task_handles_45min_label():
    client = _make_client()
    parsed = client._parse_task(_raw_task(["45min", "admin"]), inbox_project_id="p1")
    assert parsed.duration_minutes == 45
    assert parsed.labels == ["admin"]


def test_parse_task_skips_unparseable_label_silently():
    client = _make_client()
    parsed = client._parse_task(_raw_task(["bogus", "deep-work"]), inbox_project_id="p1")
    assert parsed.duration_minutes is None
    # both non-duration labels are kept
    assert parsed.labels == ["bogus", "deep-work"]


def test_parse_task_only_strips_first_duration_label():
    """If a user accidentally adds two duration labels, keep the first as the
    duration, and surface the rest on the task so the LLM can flag it."""
    client = _make_client()
    parsed = client._parse_task(_raw_task(["60min", "30min", "deep-work"]), inbox_project_id="p1")
    assert parsed.duration_minutes == 60
    assert parsed.labels == ["30min", "deep-work"]

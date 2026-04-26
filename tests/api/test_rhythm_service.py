import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "test-secret")
os.environ.setdefault("ENCRYPTION_KEY", "test-enc-key-32-chars-padding!!")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")

from unittest.mock import MagicMock
from api.services.rhythm_service import (
    get_active_rhythms,
    create_rhythm,
    update_rhythm,
    delete_rhythm,
)

_ROW = {
    "id": 1,
    "rhythm_name": "Zotero Reading",
    "sessions_per_week": 2,
    "session_min_minutes": 120,
    "session_max_minutes": 180,
    "end_date": None,
    "sort_order": 0,
    "description": None,
    "created_at": "2026-04-13T00:00:00+00:00",
    "updated_at": "2026-04-13T00:00:00+00:00",
}


def _sb_select(rows):
    """Mock for get_active_rhythms: .from_.select.eq.or_.order.execute.data"""
    sb = MagicMock()
    (sb.from_.return_value
       .select.return_value
       .eq.return_value
       .or_.return_value
       .order.return_value
       .execute.return_value.data) = rows
    return sb


def _sb_insert(row):
    """Mock for create_rhythm: .from_.insert.execute.data"""
    sb = MagicMock()
    sb.from_.return_value.insert.return_value.execute.return_value.data = [row]
    return sb


def _sb_update(row):
    """Mock for update_rhythm: .from_.update.eq.eq.select.single.execute.data"""
    sb = MagicMock()
    (sb.from_.return_value
       .update.return_value
       .eq.return_value
       .eq.return_value
       .select.return_value
       .single.return_value
       .execute.return_value.data) = row
    return sb


def test_get_active_rhythms_returns_list():
    sb = _sb_select([_ROW])
    result = get_active_rhythms("user-123", sb)
    assert len(result) == 1
    assert result[0]["rhythm_name"] == "Zotero Reading"
    assert result[0]["sessions_per_week"] == 2


def test_get_active_rhythms_empty():
    sb = _sb_select([])
    result = get_active_rhythms("user-123", sb)
    assert result == []


def test_create_rhythm_inserts_row():
    sb = _sb_insert(_ROW)
    result = create_rhythm(
        "user-123", sb,
        name="Zotero Reading",
        sessions_per_week=2,
        session_min=120,
        session_max=180,
    )
    assert result["rhythm_name"] == "Zotero Reading"
    assert result["sessions_per_week"] == 2


def test_create_rhythm_defaults():
    row = {**_ROW, "sessions_per_week": 1, "session_min_minutes": 60, "session_max_minutes": 120}
    sb = _sb_insert(row)
    result = create_rhythm("user-123", sb, name="Exercise", sessions_per_week=1)
    assert result["session_min_minutes"] == 60


def test_update_rhythm_patches_fields():
    updated = {**_ROW, "session_max_minutes": 240}
    sb = _sb_update(updated)
    result = update_rhythm("user-123", sb, rhythm_id=1, session_max=240)
    assert result["session_max_minutes"] == 240


def test_delete_rhythm_calls_delete():
    sb = MagicMock()
    delete_rhythm("user-123", sb, rhythm_id=1)
    sb.from_.assert_called_with("rhythms")
    sb.from_.return_value.delete.assert_called_once()


def test_create_rhythm_with_description():
    row = {**_ROW, "description": "Best in the morning, before deep work"}
    sb = _sb_insert(row)
    result = create_rhythm(
        "user-123", sb,
        name="Morning run",
        sessions_per_week=4,
        description="Best in the morning, before deep work",
    )
    assert result["description"] == "Best in the morning, before deep work"


def test_create_rhythm_without_description_defaults_null():
    sb = _sb_insert(_ROW)
    # _ROW has description: None
    result = create_rhythm("user-123", sb, name="Zotero Reading", sessions_per_week=2)
    insert_call_args = sb.from_.return_value.insert.call_args[0][0]
    assert insert_call_args["description"] is None


def test_update_rhythm_sets_description():
    from api.services.rhythm_service import _DESCRIPTION_UNSET
    updated = {**_ROW, "description": "After lunch works well"}
    sb = _sb_update(updated)
    result = update_rhythm("user-123", sb, rhythm_id=1, description="After lunch works well")
    assert result["description"] == "After lunch works well"


def test_update_rhythm_clears_description_when_none():
    from api.services.rhythm_service import _DESCRIPTION_UNSET
    updated = {**_ROW, "description": None}
    sb = _sb_update(updated)
    update_rhythm("user-123", sb, rhythm_id=1, description=None)
    update_call_args = sb.from_.return_value.update.call_args[0][0]
    assert "description" in update_call_args
    assert update_call_args["description"] is None


def test_update_rhythm_omitting_description_leaves_it_unchanged():
    from api.services.rhythm_service import _DESCRIPTION_UNSET
    sb = _sb_update(_ROW)
    update_rhythm("user-123", sb, rhythm_id=1, sort_order=5)
    update_call_args = sb.from_.return_value.update.call_args[0][0]
    assert "description" not in update_call_args

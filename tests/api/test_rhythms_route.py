import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "test-secret")
os.environ.setdefault("ENCRYPTION_KEY", "test-enc-key-32-chars-padding!!")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("TODOIST_CLIENT_ID", "test-todoist-id")
os.environ.setdefault("TODOIST_CLIENT_SECRET", "test-todoist-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")

from unittest.mock import patch
from fastapi.testclient import TestClient
from fastapi import FastAPI
from api.routes.rhythms import router
from api.auth import get_current_user

app = FastAPI()
app.include_router(router)

_USER = {"sub": "user-123"}
_ROW = {
    "id": 1, "rhythm_name": "Zotero Reading", "sessions_per_week": 2,
    "session_min_minutes": 120, "session_max_minutes": 180,
    "end_date": None, "sort_order": 0, "description": None,
    "created_at": "2026-04-13T00:00:00+00:00", "updated_at": "2026-04-13T00:00:00+00:00",
}

client = TestClient(app)


def _override_auth():
    app.dependency_overrides[get_current_user] = lambda: _USER


def _clear_auth():
    app.dependency_overrides.pop(get_current_user, None)


def test_list_rhythms():
    _override_auth()
    with patch("api.routes.rhythms.get_active_rhythms", return_value=[_ROW]):
        resp = client.get("/api/rhythms")
    _clear_auth()
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["rhythm_name"] == "Zotero Reading"


def test_list_rhythms_empty():
    _override_auth()
    with patch("api.routes.rhythms.get_active_rhythms", return_value=[]):
        resp = client.get("/api/rhythms")
    _clear_auth()
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_rhythm():
    _override_auth()
    with patch("api.routes.rhythms.create_rhythm", return_value=_ROW):
        resp = client.post("/api/rhythms", json={
            "name": "Zotero Reading",
            "sessions_per_week": 2,
            "session_min": 120,
            "session_max": 180,
        })
    _clear_auth()
    assert resp.status_code == 201
    assert resp.json()["rhythm_name"] == "Zotero Reading"


def test_create_rhythm_missing_required_fields():
    _override_auth()
    resp = client.post("/api/rhythms", json={"name": "Exercise"})
    _clear_auth()
    assert resp.status_code == 422


def test_update_rhythm():
    _override_auth()
    updated = {**_ROW, "session_max_minutes": 240}
    with patch("api.routes.rhythms.update_rhythm", return_value=updated):
        resp = client.patch("/api/rhythms/1", json={"session_max": 240})
    _clear_auth()
    assert resp.status_code == 200
    assert resp.json()["session_max_minutes"] == 240


def test_delete_rhythm():
    _override_auth()
    with patch("api.routes.rhythms.delete_rhythm", return_value=None):
        resp = client.delete("/api/rhythms/1")
    _clear_auth()
    assert resp.status_code == 204


def test_create_rhythm_fires_analytics():
    from unittest.mock import patch
    _override_auth()
    body = {"name": "Morning run", "sessions_per_week": 3, "session_min": 30, "session_max": 60}
    with patch("api.routes.rhythms.capture") as mock_capture, \
         patch("api.routes.rhythms.create_rhythm", return_value=_ROW):
        resp = client.post("/api/rhythms", json=body)
    _clear_auth()
    assert resp.status_code == 201
    mock_capture.assert_called_once()
    args = mock_capture.call_args[0]
    assert args[1] == "rhythm_created"
    assert args[2]["sessions_per_week"] == 3
    assert args[2]["has_end_date"] is False



def test_create_rhythm_with_description():
    _override_auth()
    row_with_desc = {**_ROW, "description": "Best in the morning"}
    with patch("api.routes.rhythms.create_rhythm", return_value=row_with_desc) as mock_create:
        resp = client.post("/api/rhythms", json={
            "name": "Morning run",
            "sessions_per_week": 4,
            "description": "Best in the morning",
        })
    _clear_auth()
    assert resp.status_code == 201
    assert resp.json()["description"] == "Best in the morning"
    _, kwargs = mock_create.call_args
    assert kwargs["description"] == "Best in the morning"


def test_create_rhythm_description_empty_string_becomes_none():
    _override_auth()
    with patch("api.routes.rhythms.create_rhythm", return_value=_ROW) as mock_create:
        resp = client.post("/api/rhythms", json={
            "name": "Morning run",
            "sessions_per_week": 4,
            "description": "",
        })
    _clear_auth()
    assert resp.status_code == 201
    _, kwargs = mock_create.call_args
    assert kwargs["description"] is None


def test_update_rhythm_sets_description():
    _override_auth()
    updated = {**_ROW, "description": "After lunch works well"}
    with patch("api.routes.rhythms.update_rhythm", return_value=updated) as mock_update:
        resp = client.patch("/api/rhythms/1", json={"description": "After lunch works well"})
    _clear_auth()
    assert resp.status_code == 200
    assert resp.json()["description"] == "After lunch works well"
    _, kwargs = mock_update.call_args
    assert kwargs["description"] == "After lunch works well"


def test_update_rhythm_clears_description_with_empty_string():
    _override_auth()
    with patch("api.routes.rhythms.update_rhythm", return_value=_ROW) as mock_update:
        resp = client.patch("/api/rhythms/1", json={"description": ""})
    _clear_auth()
    assert resp.status_code == 200
    _, kwargs = mock_update.call_args
    assert kwargs["description"] is None


def test_update_rhythm_omitting_description_passes_unset():
    """PATCH with only sort_order must not touch description in the service."""
    from api.services.rhythm_service import _DESCRIPTION_UNSET
    _override_auth()
    with patch("api.routes.rhythms.update_rhythm", return_value=_ROW) as mock_update:
        resp = client.patch("/api/rhythms/1", json={"sort_order": 2})
    _clear_auth()
    assert resp.status_code == 200
    _, kwargs = mock_update.call_args
    assert kwargs["description"] is _DESCRIPTION_UNSET

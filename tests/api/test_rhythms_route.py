import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "test-secret")
os.environ.setdefault("ENCRYPTION_KEY", "test-enc-key-32-chars-padding!!")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")

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
    "end_date": None, "sort_order": 0,
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

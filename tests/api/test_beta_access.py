import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "test-secret")
os.environ.setdefault("ENCRYPTION_KEY", "test-enc-key-32-chars-padding!!")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-gcal-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-gcal-secret")
os.environ.setdefault("TODOIST_CLIENT_ID", "test-td-id")
os.environ.setdefault("TODOIST_CLIENT_SECRET", "test-td-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.auth import get_current_user, require_beta_access
from api.config import settings


@pytest.fixture
def client():
    return TestClient(app)


def _override(user):
    app.dependency_overrides[get_current_user] = lambda: user


def _clear():
    app.dependency_overrides.pop(get_current_user, None)


def test_access_returns_allowed_when_email_in_list(client, monkeypatch):
    monkeypatch.setattr(settings, "BETA_ALLOWLIST", "alice@example.com,bob@example.com")
    _override({"sub": "u1", "email": "Alice@Example.com"})  # case-insensitive
    try:
        resp = client.get("/api/me/access")
    finally:
        _clear()
    assert resp.status_code == 200
    assert resp.json() == {"allowed": True}


def test_access_returns_rejected_when_email_not_in_list(client, monkeypatch):
    monkeypatch.setattr(settings, "BETA_ALLOWLIST", "alice@example.com")
    _override({"sub": "u2", "email": "stranger@example.com"})
    try:
        resp = client.get("/api/me/access")
    finally:
        _clear()
    assert resp.status_code == 200
    assert resp.json() == {"allowed": False, "email": "stranger@example.com"}


def test_access_open_when_allowlist_empty(client, monkeypatch):
    monkeypatch.setattr(settings, "BETA_ALLOWLIST", "")
    _override({"sub": "u3", "email": "anyone@example.com"})
    try:
        resp = client.get("/api/me/access")
    finally:
        _clear()
    assert resp.status_code == 200
    assert resp.json() == {"allowed": True}


def test_require_beta_access_passes_for_allowlisted(monkeypatch):
    monkeypatch.setattr(settings, "BETA_ALLOWLIST", "ok@x.com")
    user = {"sub": "u4", "email": "ok@x.com"}
    assert require_beta_access(user) is user


def test_require_beta_access_raises_403_for_rejected(monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(settings, "BETA_ALLOWLIST", "ok@x.com")
    with pytest.raises(HTTPException) as exc:
        require_beta_access({"sub": "u5", "email": "stranger@x.com"})
    assert exc.value.status_code == 403


def test_require_beta_access_open_when_allowlist_empty(monkeypatch):
    monkeypatch.setattr(settings, "BETA_ALLOWLIST", "")
    user = {"sub": "u6", "email": "anyone@x.com"}
    assert require_beta_access(user) is user


def test_protected_route_403_for_rejected_user(client, monkeypatch):
    """A rejected user gets 403 from a real protected route (today)."""
    monkeypatch.setattr(settings, "BETA_ALLOWLIST", "ok@x.com")
    _override({"sub": "u-stranger", "email": "stranger@x.com"})
    try:
        resp = client.get("/api/today")
    finally:
        _clear()
    assert resp.status_code == 403


def test_protected_route_passes_for_allowlisted_user(monkeypatch):
    """An allowlisted user reaches the route handler (may then 500 on missing data — that's fine)."""
    from api.main import app
    no_raise_client = TestClient(app, raise_server_exceptions=False)
    monkeypatch.setattr(settings, "BETA_ALLOWLIST", "ok@x.com")
    _override({"sub": "u-ok", "email": "ok@x.com"})
    try:
        resp = no_raise_client.get("/api/today")
    finally:
        _clear()
    # 403 would mean gating broke. Anything else (200, 500, etc.) means gating let through.
    assert resp.status_code != 403

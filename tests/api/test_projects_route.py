import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "test-secret")
os.environ.setdefault("ENCRYPTION_KEY", "test-enc-key-32-chars-padding!!")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")

from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from api.main import app
    return TestClient(app)


def test_projects_routes_registered(client):
    routes = [r.path for r in client.app.routes]
    assert "/api/projects" in routes


def test_get_projects_returns_401_without_auth(client):
    resp = client.get("/api/projects")
    assert resp.status_code == 401


def test_post_projects_returns_401_without_auth(client):
    resp = client.post("/api/projects", json={"name": "Test", "total_hours": 10.0})
    assert resp.status_code == 401

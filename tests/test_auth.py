from __future__ import annotations

import hashlib
from dataclasses import replace

from fastapi.testclient import TestClient

from alpha.main import create_app

from .conftest import campaign_payload


def test_production_session_authentication_and_csrf(settings, monkeypatch):
    monkeypatch.delenv("ALPHA_API_TOKEN", raising=False)
    secured = replace(
        settings,
        require_auth=True,
        admin_email="owner@example.com",
        admin_password="local-test-password",
        session_hours=2,
    )
    app = create_app(secured)
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/campaigns").status_code == 401
        session = client.get("/api/auth/session").json()
        assert session == {
            "required": True,
            "authenticated": False,
            "email": None,
            "expires_at": None,
        }
        wrong = client.post(
            "/api/auth/login",
            json={"email": "owner@example.com", "password": "wrong-password"},
        )
        assert wrong.status_code == 401
        login = client.post(
            "/api/auth/login",
            json={"email": "owner@example.com", "password": "local-test-password"},
        )
        assert login.status_code == 200
        session_token = client.cookies.get("alpha_session")
        csrf_token = client.cookies.get("alpha_csrf")
        assert session_token and csrf_token
        stored = app.state.db.one("SELECT * FROM app_sessions")
        assert stored["session_hash"] == hashlib.sha256(session_token.encode()).hexdigest()
        assert "local-test-password" not in str(stored)

        assert client.get("/api/campaigns").status_code == 200
        blocked = client.post("/api/campaigns", json=campaign_payload())
        assert blocked.status_code == 403
        created = client.post(
            "/api/campaigns",
            json=campaign_payload(),
            headers={"x-alpha-csrf": csrf_token},
        )
        assert created.status_code == 201, created.text
        logout = client.post("/api/auth/logout", headers={"x-alpha-csrf": csrf_token})
        assert logout.status_code == 200
        assert client.get("/api/campaigns").status_code == 401


def test_authentication_configuration_fails_closed(settings):
    incomplete = replace(settings, require_auth=True, admin_email="", admin_password="")
    try:
        create_app(incomplete)
    except RuntimeError as exc:
        assert "ALPHA_ADMIN_EMAIL" in str(exc)
    else:
        raise AssertionError("secured deployment must not start without credentials")

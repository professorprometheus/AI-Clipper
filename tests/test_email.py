from __future__ import annotations

import json
import urllib.error
from dataclasses import replace
from io import BytesIO

import pytest

import alpha.providers
from alpha.config import Settings
from alpha.pipeline import Providers
from alpha.providers import ResendEmailAdapter


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return b'{"id":"resend-email-id"}'


def test_resend_adapter_sends_text_with_bearer_and_idempotency_headers(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(alpha.providers.urllib.request, "urlopen", fake_urlopen)
    adapter = ResendEmailAdapter(
        "re_test_secret",
        "ALPHA <notifications@example.com>",
        timeout_seconds=7,
    )
    delivery_uri = adapter.send(
        "reviewer@example.com",
        "Campaign ready",
        "Three clips are ready.",
        "review-ready:campaign:job",
    )

    request = captured["request"]
    payload = json.loads(request.data)
    headers = {name.lower(): value for name, value in request.header_items()}
    assert request.full_url == "https://api.resend.com/emails"
    assert captured["timeout"] == 7
    assert headers["authorization"] == "Bearer re_test_secret"
    assert headers["idempotency-key"] == "review-ready:campaign:job"
    assert payload == {
        "from": "ALPHA <notifications@example.com>",
        "to": ["reviewer@example.com"],
        "subject": "Campaign ready",
        "text": "Three clips are ready.",
    }
    assert delivery_uri == "resend:resend-email-id"


def test_resend_provider_configuration_fails_closed(settings):
    incomplete = replace(settings, email_provider="resend", resend_api_key="re_test")
    with pytest.raises(ValueError, match="RESEND_FROM_EMAIL"):
        Providers.build(incomplete)

    unknown = replace(settings, email_provider="smtp")
    with pytest.raises(ValueError, match="Unsupported email provider"):
        Providers.build(unknown)


def test_resend_http_errors_do_not_expose_api_key(monkeypatch):
    def fail_urlopen(_request, timeout):
        assert timeout == 10
        raise urllib.error.HTTPError(
            ResendEmailAdapter.endpoint,
            422,
            "Unprocessable Entity",
            {},
            BytesIO(b'{"name":"validation_error","message":"re_test_secret"}'),
        )

    monkeypatch.setattr(alpha.providers.urllib.request, "urlopen", fail_urlopen)
    adapter = ResendEmailAdapter("re_test_secret", "ALPHA <notifications@example.com>")
    with pytest.raises(RuntimeError, match=r"HTTP 422 \(validation_error\)") as error:
        adapter.send("reviewer@example.com", "Ready", "Body", "review-ready:test")
    assert "re_test_secret" not in str(error.value)


def test_environment_auto_selects_resend_only_when_a_key_exists(monkeypatch):
    monkeypatch.setenv("ALPHA_EMAIL_PROVIDER", "auto")
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    assert Settings.from_env().email_provider == "file"

    monkeypatch.setenv("RESEND_API_KEY", "re_test_secret")
    assert Settings.from_env().email_provider == "resend"

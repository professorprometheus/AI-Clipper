from dataclasses import replace

from alpha.ops import deployment_diagnostics


def test_deployment_doctor_checks_database_storage_ffmpeg_and_auth(settings):
    result = deployment_diagnostics(settings)
    assert result["ok"]
    assert result["checks"]["database"]["migrations"] >= 7
    assert result["checks"]["storage"]["ok"]
    assert result["checks"]["ffmpeg"]["ok"]
    assert result["checks"]["authentication"]["ok"]
    assert result["checks"]["email"] == {
        "ok": True,
        "provider": "file",
        "api_key_configured": False,
        "from_address_configured": False,
    }

    incomplete_resend = deployment_diagnostics(
        replace(settings, email_provider="resend", resend_api_key="re_test")
    )
    assert not incomplete_resend["ok"]
    assert not incomplete_resend["checks"]["email"]["ok"]

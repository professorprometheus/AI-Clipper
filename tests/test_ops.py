from alpha.ops import deployment_diagnostics


def test_deployment_doctor_checks_database_storage_ffmpeg_and_auth(settings):
    result = deployment_diagnostics(settings)
    assert result["ok"]
    assert result["checks"]["database"]["migrations"] >= 7
    assert result["checks"]["storage"]["ok"]
    assert result["checks"]["ffmpeg"]["ok"]
    assert result["checks"]["authentication"]["ok"]

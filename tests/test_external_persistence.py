from __future__ import annotations

import io
from pathlib import Path

import pytest

from alpha.config import Settings
from alpha.db import Database, PostgresConnection
from alpha.providers import Renderer, S3StorageAdapter


class MemoryS3Client:
    """Small contract fake: independent adapters share remote objects, never local paths."""

    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_object(self, *, Bucket, Key, Body, **_kwargs):
        self.objects[(Bucket, Key)] = bytes(Body)

    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        self.objects[(bucket, key)] = Path(filename).read_bytes()

    def get_object(self, *, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    def download_file(self, bucket, key, filename):
        Path(filename).write_bytes(self.objects[(bucket, key)])

    def head_object(self, *, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise KeyError(Key)
        return {"ContentLength": len(self.objects[(Bucket, Key)])}

    def delete_object(self, *, Bucket, Key):
        self.objects.pop((Bucket, Key), None)

    def head_bucket(self, *, Bucket):
        return {"Bucket": Bucket}


def external_storage(client: MemoryS3Client) -> S3StorageAdapter:
    return S3StorageAdapter(
        "https://account.r2.cloudflarestorage.com",
        "auto",
        "alpha-test",
        "",
        "",
        client=client,
    )


def test_s3_contract_round_trip_and_stateless_restart(tmp_path):
    remote = MemoryS3Client()
    first_instance = external_storage(remote)
    uri = first_instance.put_bytes("sources/campaign/video.mp4", b"authorised-media", "video/mp4")
    assert uri == "s3://alpha-test/sources/campaign/video.mp4"

    with first_instance.materialize(uri) as staged:
        assert staged.read_bytes() == b"authorised-media"
        staged_path = staged
    assert not staged_path.exists()

    replacement_instance = external_storage(remote)
    assert replacement_instance.exists(uri)
    assert replacement_instance.get_bytes(uri) == b"authorised-media"
    assert b"".join(replacement_instance.iter_bytes(uri, chunk_size=4)) == b"authorised-media"
    replacement_instance.delete(uri)
    assert not replacement_instance.exists(uri)

    with pytest.raises(ValueError):
        replacement_instance.put_bytes("../escape", b"no")


def test_rendered_clip_survives_renderer_and_worker_instance_restart():
    remote = MemoryS3Client()
    first_renderer = Renderer(external_storage(remote))
    spec = {
        "duration_ms": 1000,
        "start_ms": 0,
        "source_asset_uri": None,
        "source_probe": {},
        "captions": {"enabled": False},
        "watermark": {"enabled": False},
        "headline": {"enabled": False},
    }
    rendered = first_renderer.render("campaign", "stable-variant", spec)
    assert rendered.file_uri == "s3://alpha-test/renders/campaign/stable-variant.mp4"
    assert rendered.probe["valid"]

    replacement_storage = external_storage(remote)
    assert replacement_storage.exists(rendered.file_uri)
    with replacement_storage.materialize(rendered.file_uri) as local_copy:
        assert Renderer(replacement_storage).probe_media(local_copy)["valid"]


def test_database_target_and_postgres_query_contract(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/alpha")
    monkeypatch.setenv("ALPHA_DATABASE_PATH", str(tmp_path / "ignored.db"))
    settings = Settings.from_env()
    assert settings.database_target == "postgresql://example.invalid/alpha"
    assert PostgresConnection._sql("SELECT * FROM jobs WHERE id=? AND status=?") == (
        "SELECT * FROM jobs WHERE id=%s AND status=%s"
    )


def test_sqlite_restart_still_preserves_schema_and_state(settings):
    first = Database(settings.database_target, settings.migrations_path)
    first.execute(
        "INSERT INTO connected_accounts(id,platform,display_name,adapter,created_at) "
        "VALUES (?,?,?,?,?)",
        ("restart-account", "manual", "Restart proof", "manual_export", "2026-08-15"),
    )
    replacement = Database(settings.database_target, settings.migrations_path)
    assert (
        replacement.one(
            "SELECT display_name FROM connected_accounts WHERE id=?", ("restart-account",)
        )["display_name"]
        == "Restart proof"
    )


def test_production_blueprint_is_diskless_and_worker_is_bounded():
    root = Path(__file__).resolve().parent.parent
    blueprint = (root / "render.yaml").read_text(encoding="utf-8")
    workflow = (root / ".github" / "workflows" / "alpha-worker.yml").read_text(encoding="utf-8")
    ci_workflow = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    assert "plan: free" in blueprint
    assert "disk:" not in blueprint
    for key in (
        "DATABASE_URL",
        "ALPHA_STORAGE_PROVIDER",
        "S3_ENDPOINT_URL",
        "S3_BUCKET",
        "S3_ACCESS_KEY_ID",
        "S3_SECRET_ACCESS_KEY",
    ):
        assert f"key: {key}" in blueprint
    assert "ALPHA_RUN_EMBEDDED_WORKER" in blueprint
    assert 'cron: "17 * * * *"' in workflow
    assert "timeout-minutes: 120" in workflow
    assert "Validate production configuration" in workflow
    assert "DATABASE_URL must be an external PostgreSQL URL" in workflow
    assert "python -m alpha.worker --max-stages 12" in workflow
    assert "apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core" in workflow
    assert "apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core" in ci_workflow
    assert "apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core" in dockerfile

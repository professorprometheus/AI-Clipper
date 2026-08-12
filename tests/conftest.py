from __future__ import annotations

import base64
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from alpha.config import Settings
from alpha.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    root = Path(__file__).resolve().parent.parent
    return Settings(
        database_path=tmp_path / "alpha.db",
        storage_path=tmp_path / "storage",
        email_sink_path=tmp_path / "emails",
        base_url="http://testserver",
        provider_mode="fixture",
        worker_poll_seconds=0.01,
        lease_seconds=2,
        migrations_path=root / "migrations",
        web_path=root / "web",
        retry_base_seconds=0,
        max_job_attempts=5,
    )


@pytest.fixture
def app(settings: Settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


def campaign_payload(
    *,
    source_count: int = 2,
    example_count: int = 3,
    watermark: bool = True,
) -> dict:
    sources = [
        {
            "type": "youtube_playlist" if index == 0 else "youtube_video",
            "url": (
                "https://youtube.com/playlist?list=test-list"
                if index == 0
                else f"https://youtube.com/watch?v=source-{index}"
            ),
            "title": f"Approved source {index}",
        }
        for index in range(source_count)
    ]
    examples = [
        {
            "url": f"https://examples.invalid/success-{index}",
            "platform": "fixture_social",
            "creator": f"winner-{index}",
        }
        for index in range(example_count)
    ]
    requirements = [
        {
            "key": "max_duration_seconds",
            "type": "deterministic",
            "operator": "max",
            "value": 45,
            "severity": "mandatory",
        },
        {
            "key": "watermark_present",
            "type": "deterministic",
            "operator": "eq",
            "value": True,
            "severity": "mandatory",
        },
        {
            "key": "watermark_position",
            "type": "deterministic",
            "operator": "eq",
            "value": "bottom_right",
            "severity": "mandatory",
        },
        {
            "key": "strong_hook",
            "type": "ai_evaluated",
            "operator": "eq",
            "value": True,
            "severity": "warning",
        },
    ]
    return {
        "name": "Test research campaign",
        "owner_email": "reviewer@example.com",
        "payout_value": 1.5,
        "currency": "GBP",
        "research_seeds": ["creator growth", "attention hooks"],
        "target_platforms": ["manual_export"],
        "sources": sources,
        "successful_examples": examples,
        "requirements": requirements,
        "watermark": (
            {
                "data_base64": base64.b64encode(
                    b"P6\n2 2\n255\n" + bytes([250, 204, 21] * 4)
                ).decode(),
                "filename": "fixture-watermark.ppm",
                "position": "bottom_right",
                "opacity": 0.85,
                "padding": 24,
                "size_pct": 0.18,
            }
            if watermark
            else None
        ),
    }


def generated_source_video(path: Path, duration_seconds: int = 6) -> bytes:
    import imageio_ffmpeg

    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x2459a7:s=640x360:r=24:d={duration_seconds}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=330:sample_rate=48000:duration={duration_seconds}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-y",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    return path.read_bytes()

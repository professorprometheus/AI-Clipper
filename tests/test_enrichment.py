from __future__ import annotations

import copy
import subprocess
from pathlib import Path

import imageio_ffmpeg

from alpha.db import load
from alpha.domain import analyse_enrichment_features, deterministic_qa, infer_style

from .conftest import campaign_payload, generated_source_video


def generated_music(path: Path, duration_seconds: int = 4) -> bytes:
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=220:sample_rate=48000:duration={duration_seconds}",
            "-c:a",
            "pcm_s16le",
            "-y",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    return path.read_bytes()


def upload_asset(client, campaign_id: str, asset_type: str, filename: str, content: bytes):
    response = client.post(
        f"/api/campaigns/{campaign_id}/assets",
        files={"asset": (filename, content, "application/octet-stream")},
        data={
            "asset_type": asset_type,
            "title": f"Authorised {asset_type}",
            "tags_json": '["funny", "counterexample", "creator growth"]',
            "semantic_description": "A memorable funny counterexample for creator growth",
            "licence": "User-owned test fixture licence",
            "permitted_commercial_use": "true",
            "attribution_requirement": "Test fixture attribution",
            "source_url": "https://assets.example.invalid/licence",
            "campaign_restrictions_json": "{}",
            "rights_attestation": "Test owner confirms commercial campaign usage rights.",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_enriched_campaign_renders_and_exact_review_edit_is_immutable(client, app, tmp_path):
    payload = campaign_payload(source_count=1, example_count=3)
    payload["raw_brief"] = "Use authorised media to make useful, restrained short-form clips."
    payload["enrichment"] = {
        "music_allowed": True,
        "memes_allowed": True,
        "broll_allowed": True,
        "sound_effects_allowed": False,
        "external_images_allowed": True,
        "external_video_allowed": True,
        "max_inserts": 3,
        "max_insert_duration_seconds": 2,
        "music_volume_min_db": -30,
        "music_volume_max_db": -12,
        "ducking_required": True,
    }
    created = client.post("/api/campaigns", json=payload)
    assert created.status_code == 201, created.text
    campaign_id = created.json()["id"]

    music = upload_asset(
        client,
        campaign_id,
        "music",
        "bed.wav",
        generated_music(tmp_path / "bed.wav"),
    )
    meme = upload_asset(
        client,
        campaign_id,
        "meme_image",
        "reaction.ppm",
        b"P6\n16 16\n255\n" + bytes([240, 196, 25] * 16 * 16),
    )
    broll = upload_asset(
        client,
        campaign_id,
        "broll",
        "context.mp4",
        generated_source_video(tmp_path / "context.mp4"),
    )
    assert {music["asset_type"], meme["asset_type"], broll["asset_type"]} == {
        "music",
        "meme_image",
        "broll",
    }

    client.post(f"/api/campaigns/{campaign_id}/submit")
    stages = client.post("/api/dev/worker/run-until-idle").json()
    assert stages[-1]["status"] == "awaiting_review", stages
    bundle = client.get(f"/api/campaigns/{campaign_id}/review").json()
    variant = next(
        item
        for item in bundle["variants"]
        if {"music", "meme_image", "broll", "punch_in"}
        <= {event["type"] for event in item["render_spec"]["enrichment"]["events"]}
    )
    original_spec = variant["render_spec"]
    assert original_spec["render"]["storage_verified"] is True
    assert original_spec["render"]["probe"]["valid"] is True
    assert variant["qa_status"] == "passed"
    assert client.get(f"/api/variants/{variant['id']}/media").status_code == 200
    assert variant["enrichment_plan"]["strategy_features"]["music"] is True
    assert variant["enrichment_plan"]["strategy_features"]["meme"] is True

    freeze_spec = copy.deepcopy(original_spec)
    freeze_spec.pop("render", None)
    freeze_spec["enrichment"]["events"] = [
        {
            "id": "native-freeze-check",
            "type": "freeze_frame",
            "start_ms": 4_000,
            "duration_ms": 750,
            "mode": "native",
            "purpose": "hold a key frame",
            "reason": "renderer contract check",
            "parameters": {},
        }
    ]
    freeze_render = app.state.pipeline.providers.renderer.render(
        campaign_id, "native-freeze-contract", freeze_spec
    )
    assert freeze_render.probe["valid"] is True
    assert freeze_render.probe["duration_ms"] == original_spec["duration_ms"]

    original_music = next(
        event for event in original_spec["enrichment"]["events"] if event["type"] == "music"
    )
    changed = client.post(
        f"/api/variants/{variant['id']}/review",
        json={
            "decision": "change",
            "feedback_text": (
                "remove the meme, make the music quieter and add a zoom at the punchline"
            ),
        },
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["qa_status"] == "passed"
    child_id = changed.json()["child_variant_id"]
    child = app.state.db.one("SELECT * FROM clip_variants WHERE id=?", (child_id,))
    child_spec = load(child["render_spec_json"])
    child_types = [event["type"] for event in child_spec["enrichment"]["events"]]
    assert "meme_image" not in child_types
    assert child_types.count("punch_in") >= 2
    child_music = next(
        event for event in child_spec["enrichment"]["events"] if event["type"] == "music"
    )
    assert child_music["parameters"]["volume_db"] == original_music["parameters"]["volume_db"] - 6
    assert child["parent_id"] == variant["id"]
    assert app.state.db.one(
        "SELECT id FROM enrichment_plans WHERE candidate_id=? AND version=2",
        (child["candidate_id"],),
    )
    persisted_parent = app.state.db.one(
        "SELECT render_spec_json FROM clip_variants WHERE id=?", (variant["id"],)
    )
    assert load(persisted_parent["render_spec_json"]) == original_spec


def test_enrichment_qa_blocks_unlicensed_or_prohibited_assets():
    spec = {
        "source_item_id": "approved",
        "duration_ms": 5_000,
        "aspect_ratio": "9:16",
        "width": 720,
        "height": 1280,
        "enrichment": {
            "controls": {
                "memes_allowed": False,
                "external_images_allowed": False,
                "prohibited_asset_types": ["meme_image"],
                "max_inserts": 0,
                "max_insert_duration_seconds": 1,
            },
            "events": [
                {
                    "id": "bad-meme",
                    "type": "meme_image",
                    "start_ms": 500,
                    "duration_ms": 1_000,
                    "media_kind": "image",
                    "asset_uri": "missing://asset",
                    "storage_verified": False,
                    "provenance": {
                        "licence": "",
                        "permitted_commercial_use": False,
                        "rights_attestation": "",
                    },
                }
            ],
        },
    }
    report = deterministic_qa(spec, [], {"approved"})
    assert report["passed"] is False
    failure_keys = {check["key"] for check in report["blocking_failures"]}
    assert "enrichment_insert_limit" in failure_keys
    assert "enrichment_type_permitted:bad-meme" in failure_keys
    assert "asset_rights:bad-meme" in failure_keys
    assert "asset_storage:bad-meme" in failure_keys


def test_enrichment_research_never_fabricates_unmeasured_edit_tracks():
    analysis = {
        "opening_type": "direct",
        "emotion": "humour",
        "headline": "short",
        "caption_pattern": "unavailable",
        "crop": "unavailable",
        "pacing": "fast",
        "ending": "payoff",
        "duration_seconds": 20,
        "humour": 0.9,
    }
    features = analyse_enrichment_features(analysis)
    assert features["music_presence"]["status"] == "unavailable"
    assert features["reaction_inserts"]["status"] == "inferred"
    analysis["enrichment_features"] = features
    profile = infer_style([{"id": "example-1", "analysis": analysis}])
    learned = profile["features"]["enrichment"]
    assert learned["music_presence"]["status"] == "unavailable"
    assert learned["reaction_inserts"]["status"] == "inferred"

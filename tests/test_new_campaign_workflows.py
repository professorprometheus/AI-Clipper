from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from alpha.db import dump, load
from alpha.providers import (
    AssetDiscoveryAdapter,
    DiscoveredAsset,
    OpenverseAssetDiscoveryAdapter,
    PexelsAssetDiscoveryAdapter,
    TranscriptionAdapter,
)
from alpha.services import calculate_campaign_revenue

from .conftest import campaign_payload, generated_source_video


class FixtureDiscovery(AssetDiscoveryAdapter):
    def __init__(self):
        self.search_calls = 0
        self.download_calls = 0

    def search(self, query: str, asset_types: set[str], limit: int = 8):
        self.search_calls += 1
        if not ({"meme_image", "reaction"} & asset_types):
            return []
        return [
            DiscoveredAsset(
                provider="fixturediscovery",
                provider_asset_id="reaction-1",
                asset_type="meme_image",
                title="Surprised reaction",
                tags=["funny", "surprising", "punchline"],
                semantic_description="A surprised reaction for a funny punchline",
                content_url="https://assets.example.invalid/reaction.ppm",
                source_url="https://assets.example.invalid/reaction-licence",
                licence="CC0",
                licence_url="https://creativecommons.org/publicdomain/zero/1.0/",
                attribution_requirement=None,
                permitted_commercial_use=True,
                permits_modification=True,
            )
        ]

    def download(self, asset: DiscoveredAsset):
        self.download_calls += 1
        return b"P6\n16 16\n255\n" + bytes([240, 196, 25] * 16 * 16), "image/x-portable-pixmap"


class FixtureTranscriber(TranscriptionAdapter):
    def transcribe(self, media_path: Path):
        return [
            {
                "start_ms": 0,
                "end_ms": 4500,
                "text": "A surprising automatically transcribed source moment with a payoff.",
            }
        ]


def test_live_asset_provider_contracts_filter_rights_and_use_official_endpoints(monkeypatch):
    openverse = OpenverseAssetDiscoveryAdapter()
    monkeypatch.setattr(
        openverse,
        "_json",
        lambda url, headers: {
            "results": [
                {
                    "id": "safe",
                    "title": "Safe reaction",
                    "url": "https://cdn.example/safe.jpg",
                    "foreign_landing_url": "https://source.example/safe",
                    "license": "cc0",
                    "tags": [{"name": "surprised"}],
                },
                {
                    "id": "unsafe",
                    "url": "https://cdn.example/unsafe.jpg",
                    "license": "nc",
                },
            ]
        },
    )
    results = openverse.search("surprised reaction", {"reaction"})
    assert [result.provider_asset_id for result in results] == ["safe"]
    assert results[0].permitted_commercial_use and results[0].permits_modification

    pexels = PexelsAssetDiscoveryAdapter("test-key")
    requested = []

    def pexels_json(url, headers):
        requested.append((url, headers))
        return {"videos": []}

    monkeypatch.setattr(pexels, "_json", pexels_json)
    pexels.search("creator studio", {"broll"})
    assert requested[0][0].startswith("https://api.pexels.com/videos/search?")
    assert requested[0][1]["Authorization"] == "test-key"


def test_automatic_asset_discovery_reuses_global_cache_and_omits_safely(client, app):
    payload = campaign_payload(source_count=1)
    payload["enrichment"] = {
        "memes_allowed": True,
        "external_images_allowed": True,
    }
    campaign_id = client.post("/api/campaigns", json=payload).json()["id"]
    pipeline = app.state.pipeline
    for handler in (
        pipeline.validate_campaign,
        pipeline.resolve_sources,
        pipeline.ingest_sources,
        pipeline.preflight_sources,
        pipeline.analyse_successful_examples,
        pipeline.social_research,
        pipeline.synthesize_strategy,
        pipeline.discover_candidates,
    ):
        handler(campaign_id, "asset-test")
    candidate = app.state.db.one(
        "SELECT * FROM candidate_moments WHERE campaign_id=? AND transcript LIKE '%funny%'",
        (campaign_id,),
    )
    unavailable = pipeline.build_enrichment_plan(campaign_id, candidate)
    assert not any(event["type"] == "meme_image" for event in unavailable["events"])
    assert any(
        row["type"] == "meme/reaction" and not row["used"] for row in unavailable["decisions"]
    )
    discovery = FixtureDiscovery()
    pipeline.providers.assets = discovery

    first = pipeline.build_enrichment_plan(campaign_id, candidate)
    second = pipeline.build_enrichment_plan(campaign_id, candidate, version=2)

    assert any(event["type"] == "meme_image" for event in first["events"])
    assert any(
        event.get("provenance", {}).get("provider") == "fixturediscovery"
        for event in first["events"]
    )
    assert discovery.search_calls == 1
    assert discovery.download_calls == 1
    assert app.state.db.one(
        "SELECT id FROM assets WHERE campaign_id IS NULL AND provider='fixturediscovery'"
    )
    assert any(row["type"] == "meme/reaction" and row["used"] for row in second["decisions"])

    app.state.db.execute(
        "UPDATE campaigns SET enrichment_config_json=? WHERE id=?",
        (dump({"memes_allowed": False, "external_images_allowed": False}), campaign_id),
    )
    omitted = pipeline.build_enrichment_plan(campaign_id, candidate, version=3)
    assert not any(event["type"] == "meme_image" for event in omitted["events"])
    assert any(
        row["type"] == "meme/reaction" and row["reason"] == "campaign permission is disabled"
        for row in omitted["decisions"]
    )


def test_zero_initial_candidates_broadens_to_strongest_transcript_moment(client, app):
    campaign_id = client.post("/api/campaigns", json=campaign_payload(source_count=1)).json()["id"]
    pipeline = app.state.pipeline
    pipeline.validate_campaign(campaign_id, "fallback")
    pipeline.resolve_sources(campaign_id, "fallback")
    pipeline.ingest_sources(campaign_id, "fallback")
    pipeline.preflight_sources(campaign_id, "fallback")

    result = pipeline.rank_candidates(campaign_id, "fallback")

    assert result["ranked"] == 1
    candidate = app.state.db.one(
        "SELECT * FROM candidate_moments WHERE campaign_id=?", (campaign_id,)
    )
    assert candidate["discovery_pass"] == "broad_campaign_compliant_fallback"
    assert "broadening" in candidate["selection_reason"]


def test_youtube_pasted_transcript_is_indexed_and_source_preflight_is_explicit(client, app):
    payload = campaign_payload(source_count=1)
    payload["sources"][0]["transcript"] = (
        "This is a useful opening. This is a surprising standalone payoff."
    )
    created = client.post("/api/campaigns", json=payload).json()
    campaign_id = created["id"]
    pipeline = app.state.pipeline
    pipeline.validate_campaign(campaign_id, "pasted")
    pipeline.resolve_sources(campaign_id, "pasted")
    pipeline.ingest_sources(campaign_id, "pasted")
    readiness = pipeline.preflight_sources(campaign_id, "pasted")

    assert readiness["ready_sources"] == 3
    item = app.state.db.one("SELECT * FROM source_items WHERE campaign_id=?", (campaign_id,))
    metadata = load(item["metadata_json"])
    assert metadata["transcript_timing"] == "estimated_from_video_duration"
    assert app.state.db.one(
        "SELECT COUNT(*) AS n FROM transcript_segments WHERE source_item_id=?", (item["id"],)
    )["n"]


def test_missing_live_source_material_becomes_action_required_before_research(client, app):
    payload = campaign_payload(source_count=1)
    campaign_id = client.post("/api/campaigns", json=payload).json()["id"]
    pipeline = app.state.pipeline
    pipeline.settings = replace(pipeline.settings, provider_mode="live")
    pipeline.providers.source.transcript = lambda _item, _seeds: []
    client.post(f"/api/campaigns/{campaign_id}/submit")

    results = pipeline.run_until_idle("source-preflight")

    assert results[-1]["status"] == "action_required"
    assert results[-1]["stage"] == "preflight_sources"
    assert results[-1]["error"]["code"] == "source_material_required"
    assert (
        app.state.db.one("SELECT status FROM campaigns WHERE id=?", (campaign_id,))["status"]
        == "action_required"
    )
    assert not app.state.db.one(
        "SELECT id FROM pipeline_stage_attempts WHERE job_id=? AND stage='social_research'",
        (results[-1]["job_id"],),
    )
    notification = app.state.db.one(
        "SELECT * FROM notifications WHERE campaign_id=? AND notification_type='action_required'",
        (campaign_id,),
    )
    message = json.loads(Path(notification["file_uri"]).read_text(encoding="utf-8"))
    assert "no authorised renderable video/audio" in message["body"]
    assert "Paste a transcript and upload authorised video/audio" in message["body"]


def test_youtube_uploaded_media_uses_automatic_transcription_path(client, app, tmp_path):
    payload = campaign_payload(source_count=1)
    created = client.post("/api/campaigns", json=payload).json()
    app.state.pipeline.providers.transcriber = FixtureTranscriber()
    app.state.pipeline.providers.source.transcript = lambda _item, _seeds: []
    source_bytes = generated_source_video(tmp_path / "automatic-transcription.mp4")

    response = client.post(
        f"/api/campaigns/{created['id']}/sources/import",
        files={"media": ("automatic-transcription.mp4", source_bytes, "video/mp4")},
        data={
            "rights_attestation": "I have permission to process this exact source media.",
            "external_id": "test-list-1",
        },
    )

    assert response.status_code == 201, response.text
    app.state.pipeline.validate_campaign(created["id"], "transcribe")
    app.state.pipeline.resolve_sources(created["id"], "transcribe")
    app.state.pipeline.ingest_sources(created["id"], "transcribe")
    linked = app.state.db.one(
        "SELECT * FROM linked_source_media WHERE approved_source_id=?",
        (created["sources"][0]["id"],),
    )
    assert "automatically transcribed" in json.loads(linked["transcript_json"])[0]["text"]


def test_arbitrary_payout_blocks_are_proportional_and_not_hardcoded_to_one_thousand():
    campaign = {
        "payout_model": "qualified_view_block",
        "payout_amount": 4,
        "views_per_payout_unit": 2000,
        "payout_rules_json": "{}",
    }
    assert calculate_campaign_revenue(campaign, 1500) == 3.0
    assert calculate_campaign_revenue({**campaign, "views_per_payout_unit": 1500}, 1500) == 4.0
    assert (
        calculate_campaign_revenue(
            {**campaign, "payout_rules_json": '{"rounding":"whole_blocks"}'}, 3999
        )
        == 4.0
    )


def test_normal_campaign_form_has_no_manual_enrichment_asset_catalogue():
    html = Path("web/index.html").read_text(encoding="utf-8")
    script = Path("web/app.js").read_text(encoding="utf-8")
    assert "Authorised enrichment asset library" not in html
    for obsolete in ("music_asset", "meme_asset", "broll_asset", "asset_licence", "asset_tags"):
        assert obsolete not in html
        assert obsolete not in script
    assert "Payout per qualified view" not in html
    assert "views_per_payout_unit" in script

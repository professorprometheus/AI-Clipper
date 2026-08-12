from __future__ import annotations

from pathlib import Path

from .conftest import campaign_payload, generated_source_video


def test_end_to_end_fixture_flow(client, app):
    assert client.get("/api/health").json()["status"] == "ok"
    selected_account = client.post(
        "/api/connected-accounts",
        json={
            "platform": "manual_export",
            "display_name": "Primary manual account",
            "adapter": "manual_export",
        },
    ).json()
    unselected_account = client.post(
        "/api/connected-accounts",
        json={
            "platform": "manual_export",
            "display_name": "Unselected account",
            "adapter": "manual_export",
        },
    ).json()
    payload = campaign_payload()
    payload["target_account_ids"] = [selected_account["id"]]
    created = client.post("/api/campaigns", json=payload)
    assert created.status_code == 201, created.text
    campaign_id = created.json()["id"]
    submitted = client.post(f"/api/campaigns/{campaign_id}/submit")
    assert submitted.status_code == 202

    stages = client.post("/api/dev/worker/run-until-idle").json()
    assert [row["stage"] for row in stages] == list(app.state.pipeline.stage_handlers)
    campaign = client.get(f"/api/campaigns/{campaign_id}").json()
    assert campaign["status"] == "awaiting_review"
    assert Path(campaign["watermark"]["asset_uri"]).exists()

    bundle = client.get(f"/api/campaigns/{campaign_id}/review").json()
    assert len(bundle["campaign"]["sources"]) == 2
    assert len(bundle["campaign"]["successful_examples"]) == 3
    assert bundle["strategy"]["evidence_ids"]
    assert len(bundle["variants"]) == 3
    assert all(variant["qa_status"] == "passed" for variant in bundle["variants"])
    assert all(variant["evidence_ids"] for variant in bundle["variants"])
    assert all(Path(variant["file_uri"]).exists() for variant in bundle["variants"])
    assert all(
        variant["render_spec"]["render"]["renderer"] == "ffmpeg_fixture"
        for variant in bundle["variants"]
    )

    research = client.get(f"/api/campaigns/{campaign_id}/research").json()
    outliers = [row for row in research["observations"] if row["derived"]["relative_outlier"] >= 5]
    assert len(outliers) == 3
    assert research["clusters"][0]["lifecycle_state"] == "emerging"
    huge_account = next(row for row in research["observations"] if row["creator"] == "large")
    assert huge_account["derived"]["relative_outlier"] < 2

    variant = bundle["variants"][0]
    blocked = client.post(
        f"/api/variants/{bundle['variants'][1]['id']}/publish",
        json={"platform": "manual_export", "caption": "Blocked"},
    )
    assert blocked.status_code == 409

    changed = client.post(
        f"/api/variants/{variant['id']}/review",
        json={
            "decision": "change",
            "feedback_text": "start 3 seconds earlier and make the watermark smaller",
        },
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["parsed_changes"]["watermark.size_pct"] < 0.18
    child_id = changed.json()["child_variant_id"]
    child = app.state.db.one("SELECT * FROM clip_variants WHERE id=?", (child_id,))
    assert child["parent_id"] == variant["id"]
    assert app.state.db.one("SELECT * FROM clip_variants WHERE id=?", (variant["id"],))

    approval = client.post(f"/api/variants/{child_id}/review", json={"decision": "approve"})
    assert approval.status_code == 200, approval.text
    wrong_account = client.post(
        f"/api/variants/{child_id}/publish",
        json={
            "platform": "manual_export",
            "account_id": unselected_account["id"],
            "caption": "Must remain blocked",
        },
    )
    assert wrong_account.status_code == 409
    publish_payload = {
        "platform": "manual_export",
        "account_id": selected_account["id"],
        "caption": "Human-approved export",
    }
    first = client.post(f"/api/variants/{child_id}/publish", json=publish_payload)
    second = client.post(f"/api/variants/{child_id}/publish", json=publish_payload)
    assert first.status_code == 200, first.text
    assert first.json()["id"] == second.json()["id"]
    assert Path(first.json()["export_uri"]).exists()

    publication_id = first.json()["id"]
    performance = client.post(
        f"/api/publications/{publication_id}/performance",
        json={"views": 12500, "qualified_views": 9000, "revenue": 18.5, "currency": "GBP"},
    )
    assert performance.status_code == 201
    feedback = client.post(
        f"/api/campaigns/{campaign_id}/feedback",
        json={"clip_variant_id": child_id, "rating": 5, "human_minutes": 4.5},
    )
    assert feedback.status_code == 201
    outcomes = client.get(f"/api/campaigns/{campaign_id}/outcomes").json()
    assert outcomes["records"]
    assert outcomes["summary"]["revenue_per_clip"] == 18.5
    assert outcomes["summary"]["revenue_per_human_hour"] == 246.67

    notifications = app.state.db.all(
        "SELECT * FROM notifications WHERE campaign_id=?", (campaign_id,)
    )
    assert len(notifications) == 1
    assert Path(notifications[0]["file_uri"]).exists()
    ledger = client.get("/api/research-ledger").json()
    assert any(row["policy_id"] for row in ledger)


def test_intake_supports_25_sources_and_examples_and_rejects_duplicates(client):
    response = client.post(
        "/api/campaigns", json=campaign_payload(source_count=25, example_count=25)
    )
    assert response.status_code == 201, response.text
    assert len(response.json()["sources"]) == 25
    assert len(response.json()["successful_examples"]) == 25

    duplicate = campaign_payload()
    duplicate["sources"][1]["url"] = duplicate["sources"][0]["url"]
    rejected = client.post("/api/campaigns", json=duplicate)
    assert rejected.status_code == 422
    assert "duplicate approved source" in rejected.text


def test_authorised_media_import_search_render_and_probe(client, app, tmp_path):
    import json

    payload = campaign_payload(source_count=0, example_count=2)
    created = client.post("/api/campaigns", json=payload)
    assert created.status_code == 201, created.text
    campaign_id = created.json()["id"]
    source_bytes = generated_source_video(tmp_path / "authorised-source.mp4")
    segments = [
        {
            "start_ms": 0,
            "end_ms": 2000,
            "text": "A surprising proof about creator growth opens the source.",
        },
        {
            "start_ms": 2000,
            "end_ms": 4500,
            "text": "A practical payoff closes this authorised example.",
        },
    ]
    import_payload = {
        "title": "Authorised landscape source",
        "transcript_json": json.dumps(segments),
        "rights_attestation": "I own or have permission to use this source media.",
    }
    imported = client.post(
        f"/api/campaigns/{campaign_id}/sources/import",
        files={"media": ("authorised-source.mp4", source_bytes, "video/mp4")},
        data=import_payload,
    )
    assert imported.status_code == 201, imported.text
    approved_source_id = imported.json()["id"]
    duplicate = client.post(
        f"/api/campaigns/{campaign_id}/sources/import",
        files={"media": ("authorised-source.mp4", source_bytes, "video/mp4")},
        data=import_payload,
    )
    assert duplicate.status_code == 422

    client.post(f"/api/campaigns/{campaign_id}/submit")
    results = client.post("/api/dev/worker/run-until-idle").json()
    assert results[-1]["status"] == "awaiting_review"
    search = client.get(
        f"/api/campaigns/{campaign_id}/search", params={"q": "surprising creator proof"}
    )
    assert search.status_code == 200
    assert search.json()[0]["approved_source_id"] == approved_source_id
    assert search.json()[0]["start_ms"] == 0
    assert search.json()[0]["end_ms"] == 2000

    bundle = client.get(f"/api/campaigns/{campaign_id}/review").json()
    assert bundle["variants"]
    variant = bundle["variants"][0]
    render = variant["render_spec"]["render"]
    assert render["renderer"] == "ffmpeg_authorised_source"
    assert render["probe"]["valid"]
    assert render["probe"]["width"] == 720
    assert render["probe"]["height"] == 1280
    assert render["probe"]["has_audio"]
    check_keys = {check["key"] for check in variant["deterministic_qa"]["checks"]}
    assert {"render_media_valid", "rendered_resolution", "rendered_duration"} <= check_keys
    assert variant["qa_status"] == "passed"

    spec = variant["render_spec"]
    first = app.state.pipeline.providers.renderer.render(campaign_id, "golden-a", spec)
    second = app.state.pipeline.providers.renderer.render(campaign_id, "golden-b", spec)
    assert first.sha256 == second.sha256

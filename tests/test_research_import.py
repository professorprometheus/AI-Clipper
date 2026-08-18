from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from alpha.main import create_app

from .conftest import campaign_payload, generated_source_video


def test_manual_research_import_queries_clusters_and_clipper_profiles(settings, tmp_path):
    app = create_app(replace(settings, provider_mode="manual"))
    with TestClient(app) as client:
        campaign_id = client.post("/api/campaigns", json=campaign_payload()).json()["id"]
        media = generated_source_video(tmp_path / "manual-research-source.mp4")
        source_upload = client.post(
            f"/api/campaigns/{campaign_id}/sources/import",
            files={"media": ("manual-research-source.mp4", media, "video/mp4")},
            data={
                "transcript_json": (
                    '[{"start_ms":0,"end_ms":3000,"text":"A surprising proof about creator growth."}]'
                ),
                "rights_attestation": "I own and authorise this source media for campaign clipping.",
                "title": "Authorised research source",
            },
        )
        assert source_upload.status_code == 201, source_upload.text
        observations = []
        for index in range(3):
            observations.append(
                {
                    "platform": "authorised_csv",
                    "url": f"https://research.example/posts/outlier-{index}",
                    "creator": f"clipper-{index}",
                    "published_hours_ago": 4 + index,
                    "metrics": {"views": 1500 + index * 500, "likes": 120, "comments": 20},
                    "creator_baseline": {"median_views": 100 + index * 25},
                    "transcript": "A surprising proof about creator growth.",
                    "labels": {"topic": "creator growth", "angle": "surprising proof"},
                    "raw": {"csv_row": index + 2},
                }
            )
        observations.append(
            {
                "platform": "authorised_csv",
                "url": "https://research.example/posts/large-normal",
                "creator": "large-account",
                "published_hours_ago": 24,
                "metrics": {"views": 200000, "likes": 5000, "comments": 100},
                "creator_baseline": {"median_views": 180000},
                "transcript": "Generic high-view advice.",
                "labels": {"topic": "generic advice", "angle": "routine list"},
                "raw": {"csv_row": 9},
            }
        )
        imported = client.post(
            f"/api/campaigns/{campaign_id}/research/import",
            json={
                "provenance": "User-authorised analytics CSV export dated 2026-08-10",
                "observations": observations,
            },
        )
        assert imported.status_code == 201, imported.text
        client.post(f"/api/campaigns/{campaign_id}/submit")
        results = [
            app.state.pipeline.run_once(f"manual-research-worker-{index}") for index in range(6)
        ]
        social = results[-1]
        assert social["stage"] == "social_research"
        assert social["output"]["manual_imports"] == 4
        assert social["output"]["observations"] == 4
        assert social["output"]["generated_queries"] >= 3

        report = client.get(f"/api/campaigns/{campaign_id}/research").json()
        assert len(report["observations"]) == 4
        assert any(cluster["lifecycle_state"] == "emerging" for cluster in report["clusters"])
        successful = [row for row in report["creator_profiles"] if row["successful_clipper"]]
        assert len(successful) == 3
        assert all(row["evidence_ids"] for row in successful)
        assert report["generated_queries"]
        raw = report["observations"][0]["raw"]
        derived = report["observations"][0]["derived"]
        assert "research_import_id" in raw
        assert "relative_outlier" in derived

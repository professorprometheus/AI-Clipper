from __future__ import annotations

from .config import Settings
from .db import Database
from .pipeline import Pipeline
from .schemas import CampaignCreate
from .services import AlphaService

DEMO = {
    "name": "ALPHA fixture campaign",
    "owner_email": "reviewer@example.com",
    "platform": "Content Rewards",
    "payout_model": "per_qualified_view",
    "payout_value": 1.5,
    "currency": "GBP",
    "research_seeds": ["creator growth", "attention hooks"],
    "target_platforms": ["manual_export"],
    "sources": [
        {
            "type": "youtube_playlist",
            "url": "https://youtube.com/playlist?list=alpha-demo",
            "title": "Approved demo playlist",
        },
        {
            "type": "youtube_video",
            "url": "https://youtube.com/watch?v=alpha-second",
            "title": "Approved second source",
        },
    ],
    "successful_examples": [
        {
            "url": "https://example.com/clips/winner-1",
            "platform": "fixture_social",
            "creator": "example-a",
        },
        {
            "url": "https://example.com/clips/winner-2",
            "platform": "fixture_social",
            "creator": "example-b",
        },
        {
            "url": "https://example.com/clips/winner-3",
            "platform": "fixture_social",
            "creator": "example-c",
        },
    ],
    "requirements": [
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
    ],
    "watermark": {"position": "bottom_right", "opacity": 0.85, "padding": 24, "size_pct": 0.18},
}


def main() -> None:
    settings = Settings.from_env()
    db = Database(settings.database_path, settings.migrations_path)
    pipeline = Pipeline(db, settings)
    service = AlphaService(db, pipeline)
    campaign = service.create_campaign(CampaignCreate.model_validate(DEMO))
    job = pipeline.enqueue(campaign["id"])
    results = pipeline.run_until_idle("seed")
    print(
        f"Seeded campaign {campaign['id']} with job {job['id']}; completed {len(results)} stages."
    )


if __name__ == "__main__":
    main()

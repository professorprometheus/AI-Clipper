from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

from .config import Settings
from .db import Database, load
from .pipeline import Pipeline
from .schemas import (
    CampaignCreate,
    ExperimentInput,
    FeedbackInput,
    PerformanceInput,
    PublishInput,
    ReviewInput,
)
from .services import AlphaService


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    db = Database(settings.database_path, settings.migrations_path)
    pipeline = Pipeline(db, settings)
    service = AlphaService(db, pipeline)
    api = FastAPI(title="ALPHA V0", version="0.1.0")
    api.state.settings = settings
    api.state.db = db
    api.state.pipeline = pipeline
    api.state.service = service
    requests_by_ip: dict[str, deque[float]] = defaultdict(deque)

    @api.middleware("http")
    async def security_and_rate_limit(request: Request, call_next):
        if request.url.path.startswith("/api/") and request.url.path != "/api/health":
            configured_token = os.getenv("ALPHA_API_TOKEN")
            if configured_token and request.headers.get("x-alpha-token") != configured_token:
                raise HTTPException(status_code=401, detail="invalid or missing API token")
            address = request.client.host if request.client else "unknown"
            bucket = requests_by_ip[address]
            cutoff = time.monotonic() - 60
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= 180:
                raise HTTPException(status_code=429, detail="rate limit exceeded")
            bucket.append(time.monotonic())
        return await call_next(request)

    @api.exception_handler(KeyError)
    async def key_error(_request: Request, exc: KeyError):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=404, content={"detail": str(exc).strip("'")})

    @api.exception_handler(PermissionError)
    async def permission_error(_request: Request, exc: PermissionError):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @api.get("/api/health")
    def health() -> dict[str, Any]:
        migration = db.one("SELECT COUNT(*) AS n FROM schema_migrations")
        return {"status": "ok", "version": "0.1.0", "database": "ok", "migrations": migration["n"]}

    @api.post("/api/campaigns", status_code=201)
    def create_campaign(payload: CampaignCreate):
        try:
            return service.create_campaign(payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @api.get("/api/campaigns")
    def list_campaigns():
        return service.list_campaigns()

    @api.get("/api/campaigns/{campaign_id}")
    def get_campaign(campaign_id: str):
        return service.get_campaign(campaign_id)

    @api.patch("/api/campaigns/{campaign_id}")
    def edit_campaign(campaign_id: str, changes: dict[str, Any]):
        return service.edit_campaign(campaign_id, changes)

    @api.post("/api/campaigns/{campaign_id}/submit", status_code=202)
    def submit_campaign(campaign_id: str):
        service.get_campaign(campaign_id)
        return pipeline.enqueue(campaign_id)

    @api.post("/api/dev/worker/run-one")
    def run_worker_once():
        return pipeline.run_once("api-dev-worker") or {"status": "idle"}

    @api.post("/api/dev/worker/run-until-idle")
    def run_worker_until_idle():
        return pipeline.run_until_idle("api-dev-worker")

    @api.get("/api/campaigns/{campaign_id}/review")
    def review_bundle(campaign_id: str):
        return service.review_bundle(campaign_id)

    @api.post("/api/variants/{variant_id}/review")
    def review_variant(variant_id: str, payload: ReviewInput):
        return service.review(variant_id, payload)

    @api.post("/api/variants/{variant_id}/publish")
    def publish_variant(variant_id: str, payload: PublishInput):
        return service.publish(variant_id, payload)

    @api.get("/api/variants/{variant_id}/media")
    def variant_media(variant_id: str):
        variant = db.one("SELECT file_uri FROM clip_variants WHERE id=?", (variant_id,))
        if not variant:
            raise KeyError("clip variant not found")
        path = Path(variant["file_uri"]).resolve()
        root = settings.storage_path.resolve()
        if root not in path.parents or not path.exists():
            raise KeyError("clip media not found")
        return FileResponse(
            path, media_type="video/mp4" if path.suffix == ".mp4" else "application/json"
        )

    @api.post("/api/campaigns/{campaign_id}/feedback", status_code=201)
    def record_feedback(campaign_id: str, payload: FeedbackInput):
        service.get_campaign(campaign_id)
        return service.record_feedback(campaign_id, payload)

    @api.post("/api/publications/{publication_id}/performance", status_code=201)
    def record_performance(publication_id: str, payload: PerformanceInput):
        return service.record_performance(publication_id, payload)

    @api.get("/api/campaigns/{campaign_id}/outcomes")
    def campaign_outcomes(campaign_id: str):
        service.get_campaign(campaign_id)
        return service.outcomes(campaign_id)

    @api.get("/api/campaigns/{campaign_id}/research")
    def campaign_research(campaign_id: str):
        service.get_campaign(campaign_id)
        observations = db.all(
            "SELECT * FROM research_observations WHERE campaign_id=? ORDER BY observed_at",
            (campaign_id,),
        )
        for row in observations:
            for key in ("metrics_json", "baseline_json", "raw_json", "derived_json", "labels_json"):
                row[key.removesuffix("_json")] = load(row.pop(key), {})
        clusters = db.all("SELECT * FROM trend_clusters WHERE campaign_id=?", (campaign_id,))
        for row in clusters:
            row["metrics"] = load(row.pop("metrics_json"), {})
            row["evidence_ids"] = load(row.pop("evidence_ids_json"), [])
        return {"observations": observations, "clusters": clusters}

    @api.get("/api/research-ledger")
    def research_ledger():
        rows = db.all("SELECT * FROM research_ledger ORDER BY created_at DESC")
        for row in rows:
            row["evidence"] = load(row.pop("evidence_json"), {})
            row["applies_to"] = load(row.pop("applies_to_json"), {})
        return rows

    @api.post("/api/experiments", status_code=201)
    def create_experiment(payload: ExperimentInput):
        return service.create_experiment(payload)

    @api.post("/api/experiments/{experiment_id}/evaluate")
    def evaluate_experiment(experiment_id: str, payload: dict[str, Any]):
        return service.evaluate_experiment(
            experiment_id,
            bool(payload.get("activate_treatment")),
            str(payload.get("summary", "Evaluated manually.")),
        )

    @api.post("/api/policies/{policy_id}/activate")
    def activate_policy(policy_id: str, payload: dict[str, Any]):
        return service.activate_policy(
            policy_id, str(payload.get("reason", "Manual auditable policy activation"))
        )

    @api.get("/")
    def index():
        return FileResponse(settings.web_path / "index.html")

    @api.get("/app.js")
    def app_js():
        return FileResponse(settings.web_path / "app.js", media_type="text/javascript")

    @api.get("/styles.css")
    def styles():
        return FileResponse(settings.web_path / "styles.css", media_type="text/css")

    return api


app = create_app()


def run() -> None:
    uvicorn.run("alpha.main:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    run()

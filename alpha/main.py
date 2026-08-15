from __future__ import annotations

import hashlib
import hmac
import mimetypes
import os
import secrets
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from typing import Any

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from .config import Settings
from .db import Database, load, now, uid
from .pipeline import Pipeline
from .schemas import (
    CampaignCreate,
    ConnectedAccountCreate,
    ExperimentInput,
    FeedbackInput,
    LoginInput,
    PerformanceInput,
    PublishInput,
    RequirementUpdate,
    ResearchImportBatch,
    ReviewInput,
)
from .services import AlphaService


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    if settings.require_auth and not (settings.admin_email and settings.admin_password):
        raise RuntimeError("ALPHA_REQUIRE_AUTH needs ALPHA_ADMIN_EMAIL and ALPHA_ADMIN_PASSWORD")
    db = Database(settings.database_target, settings.migrations_path)
    pipeline = Pipeline(db, settings)
    service = AlphaService(db, pipeline)
    api = FastAPI(title="ALPHA V0", version="0.1.0")
    api.state.settings = settings
    api.state.db = db
    api.state.pipeline = pipeline
    api.state.service = service
    requests_by_ip: dict[str, deque[float]] = defaultdict(deque)

    def token_hash(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @api.middleware("http")
    async def security_and_rate_limit(request: Request, call_next):
        if request.url.path.startswith("/api/") and request.url.path != "/api/health":
            configured_token = os.getenv("ALPHA_API_TOKEN")
            address = request.client.host if request.client else "unknown"
            bucket = requests_by_ip[address]
            cutoff = time.monotonic() - 60
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= 180:
                return JSONResponse(status_code=429, content={"detail": "rate limit exceeded"})
            bucket.append(time.monotonic())
            supplied_token = request.headers.get("x-alpha-token", "")
            token_authenticated = bool(
                configured_token
                and supplied_token
                and hmac.compare_digest(supplied_token, configured_token)
            )
            if configured_token and not settings.require_auth and not token_authenticated:
                return JSONResponse(
                    status_code=401, content={"detail": "invalid or missing API token"}
                )
            public_auth_paths = {"/api/auth/login", "/api/auth/session"}
            if (
                settings.require_auth
                and not token_authenticated
                and request.url.path not in public_auth_paths
            ):
                session_token = request.cookies.get("alpha_session", "")
                session = (
                    db.one(
                        "SELECT * FROM app_sessions WHERE session_hash=? AND revoked_at IS NULL AND expires_at>?",
                        (token_hash(session_token), now()),
                    )
                    if session_token
                    else None
                )
                if not session:
                    return JSONResponse(
                        status_code=401, content={"detail": "authentication required"}
                    )
                if request.method not in {"GET", "HEAD", "OPTIONS"}:
                    csrf = request.headers.get("x-alpha-csrf", "")
                    if not csrf or not hmac.compare_digest(token_hash(csrf), session["csrf_hash"]):
                        return JSONResponse(
                            status_code=403, content={"detail": "valid CSRF token required"}
                        )
                db.execute(
                    "UPDATE app_sessions SET last_seen_at=? WHERE id=?", (now(), session["id"])
                )
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

    @api.get("/api/auth/session")
    def auth_session(request: Request):
        if not settings.require_auth:
            return {"required": False, "authenticated": True, "email": None}
        session_token = request.cookies.get("alpha_session", "")
        session = (
            db.one(
                "SELECT email,expires_at FROM app_sessions "
                "WHERE session_hash=? AND revoked_at IS NULL AND expires_at>?",
                (token_hash(session_token), now()),
            )
            if session_token
            else None
        )
        return {
            "required": True,
            "authenticated": bool(session),
            "email": session["email"] if session else None,
            "expires_at": session["expires_at"] if session else None,
        }

    @api.post("/api/auth/login")
    def login(payload: LoginInput):
        email_valid = hmac.compare_digest(str(payload.email).lower(), settings.admin_email.lower())
        password_valid = hmac.compare_digest(payload.password, settings.admin_password)
        if not settings.require_auth or not (email_valid and password_valid):
            return JSONResponse(status_code=401, content={"detail": "invalid credentials"})
        session_token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        timestamp = now()
        expires = (datetime.now(UTC) + timedelta(hours=max(1, settings.session_hours))).isoformat()
        db.execute(
            "INSERT INTO app_sessions(id,session_hash,csrf_hash,email,expires_at,created_at,last_seen_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                uid(),
                token_hash(session_token),
                token_hash(csrf_token),
                settings.admin_email,
                expires,
                timestamp,
                timestamp,
            ),
        )
        response = JSONResponse(
            {"authenticated": True, "email": settings.admin_email, "expires_at": expires}
        )
        response.set_cookie(
            "alpha_session",
            session_token,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="strict",
            max_age=max(1, settings.session_hours) * 3600,
        )
        response.set_cookie(
            "alpha_csrf",
            csrf_token,
            httponly=False,
            secure=settings.cookie_secure,
            samesite="strict",
            max_age=max(1, settings.session_hours) * 3600,
        )
        return response

    @api.post("/api/auth/logout")
    def logout(request: Request):
        session_token = request.cookies.get("alpha_session", "")
        if session_token:
            db.execute(
                "UPDATE app_sessions SET revoked_at=? WHERE session_hash=? AND revoked_at IS NULL",
                (now(), token_hash(session_token)),
            )
        response = JSONResponse({"authenticated": False})
        response.delete_cookie("alpha_session")
        response.delete_cookie("alpha_csrf")
        return response

    @api.post("/api/campaigns", status_code=201)
    def create_campaign(payload: CampaignCreate):
        try:
            return service.create_campaign(payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @api.get("/api/campaigns")
    def list_campaigns():
        return service.list_campaigns()

    @api.post("/api/connected-accounts", status_code=201)
    def create_connected_account(payload: ConnectedAccountCreate):
        return service.create_connected_account(payload)

    @api.get("/api/connected-accounts")
    def list_connected_accounts():
        return db.all("SELECT * FROM connected_accounts ORDER BY created_at")

    @api.post("/api/campaigns/{campaign_id}/accounts/{account_id}")
    def attach_connected_account(campaign_id: str, account_id: str):
        return service.attach_connected_account(campaign_id, account_id)

    @api.get("/api/campaigns/{campaign_id}")
    def get_campaign(campaign_id: str):
        return service.get_campaign(campaign_id)

    @api.patch("/api/campaigns/{campaign_id}")
    def edit_campaign(campaign_id: str, changes: dict[str, Any]):
        return service.edit_campaign(campaign_id, changes)

    @api.patch("/api/campaigns/{campaign_id}/requirements/{requirement_id}")
    def revise_requirement(campaign_id: str, requirement_id: str, payload: RequirementUpdate):
        return service.revise_requirement(campaign_id, requirement_id, payload)

    @api.post("/api/campaigns/{campaign_id}/sources/import", status_code=201)
    async def import_authorised_source(
        campaign_id: str,
        media: UploadFile = File(...),
        transcript_json: str = Form(...),
        rights_attestation: str = Form(...),
        title: str | None = Form(default=None),
        approved_source_id: str | None = Form(default=None),
        external_id: str | None = Form(default=None),
    ):
        try:
            content = await media.read()
            return service.import_authorised_source(
                campaign_id,
                media.filename or "source.mp4",
                media.content_type or "application/octet-stream",
                content,
                transcript_json,
                rights_attestation,
                title,
                approved_source_id,
                external_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @api.get("/api/campaigns/{campaign_id}/search")
    def semantic_search(
        campaign_id: str,
        q: str = Query(min_length=1, max_length=500),
        limit: int = Query(default=10, ge=1, le=100),
    ):
        return service.semantic_search(campaign_id, q, limit)

    @api.post("/api/campaigns/{campaign_id}/research/import", status_code=201)
    def import_research(campaign_id: str, payload: ResearchImportBatch):
        try:
            return service.import_research(campaign_id, payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

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
        uri = variant["file_uri"]
        if not uri or not pipeline.providers.storage.exists(uri):
            raise KeyError("clip media not found")
        return StreamingResponse(
            pipeline.providers.storage.iter_bytes(uri),
            media_type=mimetypes.guess_type(uri)[0] or "application/octet-stream",
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
        creators = db.all("SELECT * FROM creator_profiles WHERE campaign_id=?", (campaign_id,))
        for row in creators:
            row["metrics"] = load(row.pop("metrics_json"), {})
            row["evidence_ids"] = load(row.pop("evidence_ids_json"), [])
        queries = db.all(
            "SELECT id,target_type,value FROM research_targets "
            "WHERE campaign_id=? AND target_type='generated_query' ORDER BY value",
            (campaign_id,),
        )
        provider_events = db.all(
            "SELECT provider,operation,status,details_json,created_at FROM provider_events "
            "WHERE campaign_id=? ORDER BY created_at",
            (campaign_id,),
        )
        for row in provider_events:
            row["details"] = load(row.pop("details_json"), {})
        return {
            "observations": observations,
            "clusters": clusters,
            "creator_profiles": creators,
            "generated_queries": queries,
            "provider_events": provider_events,
        }

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

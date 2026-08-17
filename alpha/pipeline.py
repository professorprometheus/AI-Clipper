from __future__ import annotations

import hashlib
import logging
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .config import Settings
from .db import Database, dump, load, now, uid
from .domain import (
    DEFAULT_WEIGHTS,
    analyse_enrichment_features,
    candidate_scores,
    cluster_observations,
    cosine,
    deterministic_qa,
    embedding,
    enrichment_suitability,
    infer_style,
    research_signals,
    weighted_score,
)
from .live_providers import LiveResearchProvider, YouTubeAPIClient, YouTubeSourceProvider
from .providers import (
    AIAdapter,
    EmailAdapter,
    FileEmailAdapter,
    FixtureResearchProvider,
    FixtureSourceProvider,
    LocalHeuristicAIAdapter,
    ManualExportAdapter,
    ManualImportSourceProvider,
    ManualResearchProvider,
    PublicationAdapter,
    Renderer,
    ResearchProvider,
    ResendEmailAdapter,
    SourceProvider,
    StorageAdapter,
    build_storage,
    stable_id,
)

logger = logging.getLogger("alpha.pipeline")

STAGES = [
    "validate_campaign",
    "resolve_sources",
    "ingest_sources",
    "analyse_successful_examples",
    "social_research",
    "synthesize_strategy",
    "discover_candidates",
    "rank_candidates",
    "plan_enrichment",
    "render",
    "qa",
    "review_ready",
]


def redact_secrets(message: str) -> str:
    patterns = [
        r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|secret)\s*[:=]\s*[^\s,;&]+",
        r"(?i)bearer\s+[a-z0-9._~+/-]+=*",
    ]
    redacted = message
    for pattern in patterns:
        redacted = re.sub(
            pattern,
            lambda match: (
                f"{match.group(1)}=[REDACTED]" if match.lastindex else "Bearer [REDACTED]"
            ),
            redacted,
        )
    return redacted[:2000]


@dataclass
class Providers:
    storage: StorageAdapter
    source: SourceProvider
    research: ResearchProvider
    email: EmailAdapter
    publication: PublicationAdapter
    renderer: Renderer
    ai: AIAdapter

    @classmethod
    def build(cls, settings: Settings) -> Providers:
        storage = build_storage(settings)
        if settings.provider_mode == "fixture":
            source: SourceProvider = FixtureSourceProvider()
            research: ResearchProvider = FixtureResearchProvider()
        elif settings.provider_mode == "live":
            youtube = YouTubeAPIClient(
                settings.youtube_api_key,
                settings.youtube_oauth_access_token,
                settings.youtube_oauth_client_id,
                settings.youtube_oauth_client_secret,
                settings.youtube_oauth_refresh_token,
            )
            source = YouTubeSourceProvider(youtube)
            research = LiveResearchProvider(
                youtube,
                tiktok_token=settings.tiktok_research_access_token,
                tiktok_client_key=settings.tiktok_client_key,
                tiktok_client_secret=settings.tiktok_client_secret,
                instagram_token=settings.instagram_access_token,
                instagram_user_id=settings.instagram_user_id,
                region=settings.research_region,
                lookback_days=settings.research_lookback_days,
                results_per_query=settings.research_results_per_query,
            )
        elif settings.provider_mode == "manual":
            source = ManualImportSourceProvider()
            research = ManualResearchProvider()
        else:
            raise ValueError(f"Unsupported provider mode: {settings.provider_mode}")
        if settings.email_provider == "file":
            email: EmailAdapter = FileEmailAdapter(settings.email_sink_path)
        elif settings.email_provider == "resend":
            email = ResendEmailAdapter(
                settings.resend_api_key,
                settings.resend_from_email,
                settings.email_timeout_seconds,
            )
        else:
            raise ValueError(f"Unsupported email provider: {settings.email_provider}")
        return cls(
            storage=storage,
            source=source,
            research=research,
            email=email,
            publication=ManualExportAdapter(storage),
            renderer=Renderer(storage),
            ai=LocalHeuristicAIAdapter(),
        )


class Pipeline:
    def __init__(self, db: Database, settings: Settings, providers: Providers | None = None):
        self.db = db
        self.settings = settings
        self.providers = providers or Providers.build(settings)
        self.stage_handlers: dict[str, Callable[[str, str], dict[str, Any]]] = {
            "validate_campaign": self.validate_campaign,
            "resolve_sources": self.resolve_sources,
            "ingest_sources": self.ingest_sources,
            "analyse_successful_examples": self.analyse_successful_examples,
            "social_research": self.social_research,
            "synthesize_strategy": self.synthesize_strategy,
            "discover_candidates": self.discover_candidates,
            "rank_candidates": self.rank_candidates,
            "plan_enrichment": self.plan_enrichment,
            "render": self.render,
            "qa": self.qa,
            "review_ready": self.review_ready,
        }
        self.ensure_default_policy()

    def ensure_default_policy(self) -> str:
        row = self.db.one(
            "SELECT id FROM strategy_policies WHERE active=1 ORDER BY version DESC LIMIT 1"
        )
        if row:
            return row["id"]
        policy_id = uid()
        self.db.execute(
            "INSERT INTO strategy_policies(id,version,weights_json,exploration_pct,active,created_at) "
            "VALUES (?,?,?,?,?,?)",
            (policy_id, 1, dump(DEFAULT_WEIGHTS), 0.15, 1, now()),
        )
        return policy_id

    def enqueue(self, campaign_id: str) -> dict[str, Any]:
        idempotency_key = f"campaign-pipeline:{campaign_id}"
        existing = self.db.one(
            "SELECT * FROM pipeline_jobs WHERE idempotency_key=?", (idempotency_key,)
        )
        if existing:
            return existing
        timestamp = now()
        job_id = uid()
        self.db.execute(
            "INSERT INTO pipeline_jobs(id,campaign_id,job_type,status,current_stage,checkpoint_json,"
            "idempotency_key,available_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                job_id,
                campaign_id,
                "campaign_pipeline",
                "queued",
                STAGES[0],
                dump({"completed_stages": []}),
                idempotency_key,
                timestamp,
                timestamp,
                timestamp,
            ),
        )
        self.db.execute(
            "UPDATE campaigns SET status='processing',updated_at=? WHERE id=?", (now(), campaign_id)
        )
        self.db.audit("campaign", campaign_id, "pipeline_enqueued", {"job_id": job_id})
        return self.db.one("SELECT * FROM pipeline_jobs WHERE id=?", (job_id,)) or {}

    def retry_failed(self, campaign_id: str) -> dict[str, Any]:
        job = self.db.one(
            "SELECT * FROM pipeline_jobs WHERE campaign_id=? ORDER BY created_at DESC LIMIT 1",
            (campaign_id,),
        )
        if not job:
            raise KeyError("campaign job not found")
        if job["status"] != "failed":
            raise PermissionError("only a failed campaign job can be retried")
        timestamp = now()
        updated = self.db.execute(
            "UPDATE pipeline_jobs SET status='queued',attempts=0,error_json=NULL,available_at=?,"
            "worker_token=NULL,lease_expires_at=NULL,heartbeat_at=NULL,updated_at=? "
            "WHERE id=? AND status='failed'",
            (timestamp, timestamp, job["id"]),
        )
        if not updated:
            raise PermissionError("campaign job is no longer failed")
        self.db.execute(
            "UPDATE campaigns SET status='processing',updated_at=? WHERE id=?",
            (timestamp, campaign_id),
        )
        self.db.audit(
            "campaign",
            campaign_id,
            "failed_stage_requeued",
            {"job_id": job["id"], "stage": job["current_stage"]},
        )
        return self.db.one("SELECT * FROM pipeline_jobs WHERE id=?", (job["id"],)) or {}

    def acquire(self, worker_token: str) -> dict[str, Any] | None:
        timestamp = now()
        lease = (datetime.now(UTC) + timedelta(seconds=self.settings.lease_seconds)).isoformat()
        with self.db.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM pipeline_jobs WHERE "
                "status='queued' OR (status='retry' AND (available_at IS NULL OR available_at<=?)) "
                "OR (status='leased' AND lease_expires_at < ?) "
                f"ORDER BY created_at LIMIT 1{self.db.acquire_lock_clause}",
                (timestamp, timestamp),
            ).fetchone()
            if not row:
                return None
            job = dict(row)
            connection.execute(
                "UPDATE pipeline_jobs SET status='leased',worker_token=?,lease_expires_at=?,"
                "heartbeat_at=?,available_at=NULL,updated_at=? WHERE id=?",
                (worker_token, lease, timestamp, timestamp, job["id"]),
            )
            job.update(
                {"status": "leased", "worker_token": worker_token, "lease_expires_at": lease}
            )
            return job

    def heartbeat(self, job_id: str, worker_token: str) -> bool:
        lease = (datetime.now(UTC) + timedelta(seconds=self.settings.lease_seconds)).isoformat()
        return bool(
            self.db.execute(
                "UPDATE pipeline_jobs SET heartbeat_at=?,lease_expires_at=?,updated_at=? "
                "WHERE id=? AND worker_token=? AND status='leased'",
                (now(), lease, now(), job_id, worker_token),
            )
        )

    def run_once(self, worker_token: str = "worker") -> dict[str, Any] | None:
        job = self.acquire(worker_token)
        if not job:
            return None
        stage = job["current_stage"]
        stage_run_id = uid()
        started = now()
        self.db.execute(
            "INSERT INTO pipeline_stage_attempts(id,job_id,stage,status,attempt,worker_token,output_json,started_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                stage_run_id,
                job["id"],
                stage,
                "running",
                job["attempts"] + 1,
                worker_token,
                "{}",
                started,
            ),
        )
        logger.info(dump({"event": "stage_started", "job_id": job["id"], "stage": stage}))
        stop_heartbeat = threading.Event()
        lease_lost = threading.Event()

        def renew_lease() -> None:
            interval = max(0.1, self.settings.lease_seconds / 3)
            consecutive_failures = 0
            while not stop_heartbeat.wait(interval):
                try:
                    if self.heartbeat(job["id"], worker_token):
                        consecutive_failures = 0
                        self.db.execute(
                            "UPDATE pipeline_stage_attempts SET heartbeat_count=heartbeat_count+1 WHERE id=?",
                            (stage_run_id,),
                        )
                    else:
                        consecutive_failures += 1
                except Exception:
                    consecutive_failures += 1
                    logger.warning(
                        dump(
                            {
                                "event": "heartbeat_failed",
                                "job_id": job["id"],
                                "stage": stage,
                                "consecutive_failures": consecutive_failures,
                            }
                        )
                    )
                if consecutive_failures >= 3:
                    lease_lost.set()
                    return

        heartbeat_thread = threading.Thread(
            target=renew_lease,
            name=f"alpha-heartbeat-{job['id']}",
            daemon=True,
        )
        heartbeat_thread.start()
        try:
            output = self.stage_handlers[stage](job["campaign_id"], job["id"])
            stop_heartbeat.set()
            heartbeat_thread.join(timeout=max(1.0, self.settings.lease_seconds))
            if lease_lost.is_set():
                self.db.execute(
                    "UPDATE pipeline_stage_attempts SET status='lease_lost',output_json=?,completed_at=? WHERE id=?",
                    (dump({"stage_output": output}), now(), stage_run_id),
                )
                return {"job_id": job["id"], "stage": stage, "status": "lease_lost"}
            checkpoint = load(job["checkpoint_json"], {"completed_stages": []})
            completed = list(dict.fromkeys([*checkpoint.get("completed_stages", []), stage]))
            checkpoint.update({"completed_stages": completed, "last_output": output})
            index = STAGES.index(stage)
            final = index == len(STAGES) - 1
            next_stage = stage if final else STAGES[index + 1]
            status = "awaiting_review" if final else "queued"
            updated = self.db.execute(
                "UPDATE pipeline_jobs SET status=?,current_stage=?,checkpoint_json=?,worker_token=NULL,"
                "lease_expires_at=NULL,available_at=?,error_json=NULL,attempts=0,updated_at=? "
                "WHERE id=? AND worker_token=? AND status='leased'",
                (status, next_stage, dump(checkpoint), now(), now(), job["id"], worker_token),
            )
            if not updated:
                self.db.execute(
                    "UPDATE pipeline_stage_attempts SET status='lease_lost',output_json=?,completed_at=? WHERE id=?",
                    (dump({"stage_output": output}), now(), stage_run_id),
                )
                return {"job_id": job["id"], "stage": stage, "status": "lease_lost"}
            self.db.execute(
                "UPDATE pipeline_stage_attempts SET status='completed',output_json=?,completed_at=? WHERE id=?",
                (dump(output), now(), stage_run_id),
            )
            logger.info(dump({"event": "stage_completed", "job_id": job["id"], "stage": stage}))
            return {"job_id": job["id"], "stage": stage, "status": status, "output": output}
        except Exception as exc:
            stop_heartbeat.set()
            heartbeat_thread.join(timeout=max(1.0, self.settings.lease_seconds))
            attempts = int(job["attempts"]) + 1
            deterministic_failure = isinstance(exc, (KeyError, PermissionError, ValueError))
            status = (
                "failed"
                if deterministic_failure or attempts >= self.settings.max_job_attempts
                else "retry"
            )
            backoff_seconds = min(
                300.0,
                max(0.0, self.settings.retry_base_seconds) * (2 ** max(0, attempts - 1)),
            )
            available_at = (datetime.now(UTC) + timedelta(seconds=backoff_seconds)).isoformat()
            error = {
                "type": type(exc).__name__,
                "message": redact_secrets(str(exc)),
                "stage": stage,
                "retryable": status == "retry",
            }
            updated = self.db.execute(
                "UPDATE pipeline_jobs SET status=?,attempts=?,error_json=?,worker_token=NULL,"
                "lease_expires_at=NULL,available_at=?,updated_at=? "
                "WHERE id=? AND worker_token=? AND status='leased'",
                (
                    status,
                    attempts,
                    dump(error),
                    available_at,
                    now(),
                    job["id"],
                    worker_token,
                ),
            )
            self.db.execute(
                "UPDATE pipeline_stage_attempts SET status='failed',output_json=?,completed_at=? WHERE id=?",
                (dump(error), now(), stage_run_id),
            )
            if status == "failed" and updated:
                self._notify_terminal_failure(job, stage, error)
            logger.error(
                dump(
                    {
                        "event": "stage_failed",
                        "job_id": job["id"],
                        "stage": stage,
                        "error": error,
                    }
                )
            )
            return {"job_id": job["id"], "stage": stage, "status": status, "error": error}

    def _notify_terminal_failure(
        self, job: dict[str, Any], stage: str, error: dict[str, Any]
    ) -> None:
        campaign = self._campaign(job["campaign_id"])
        key = f"failed-needs-attention:{job['id']}:{stage}"
        if self.db.one("SELECT id FROM notifications WHERE idempotency_key=?", (key,)):
            return
        body = (
            f"ALPHA could not complete stage '{stage}' after bounded retries. "
            f"Error class: {error['type']}. Open the campaign: "
            f"{self.settings.base_url}/?campaign={job['campaign_id']}"
        )
        uri = self.providers.email.send(
            campaign["owner_email"],
            f"{campaign['name']} needs attention",
            body,
            key,
        )
        self.db.execute(
            "INSERT INTO notifications(id,campaign_id,notification_type,idempotency_key,recipient,file_uri,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                uid(),
                job["campaign_id"],
                "failed_needs_attention",
                key,
                campaign["owner_email"],
                uri,
                now(),
            ),
        )
        self.db.execute(
            "UPDATE campaigns SET status='failed_needs_attention',updated_at=? WHERE id=?",
            (now(), job["campaign_id"]),
        )

    def run_until_idle(
        self, worker_token: str = "worker", limit: int = 100
    ) -> list[dict[str, Any]]:
        results = []
        for index in range(limit):
            result = self.run_once(f"{worker_token}-{index % 3}")
            if result is None:
                break
            results.append(result)
            if result["status"] == "failed":
                break
        return results

    def _campaign(self, campaign_id: str) -> dict[str, Any]:
        campaign = self.db.one("SELECT * FROM campaigns WHERE id=?", (campaign_id,))
        if not campaign:
            raise ValueError("campaign not found")
        return campaign

    def _requirements(self, campaign_id: str) -> list[dict[str, Any]]:
        rows = self.db.all(
            "SELECT * FROM campaign_requirements WHERE campaign_id=?", (campaign_id,)
        )
        for row in rows:
            row["value"] = load(row.pop("value_json"))
        return rows

    def _record_provider_events(self, campaign_id: str, provider: Any) -> None:
        events = list(getattr(provider, "last_events", []))
        for event in events:
            details = {
                key: redact_secrets(str(value)) if key == "error" else value
                for key, value in event.items()
                if key not in {"provider", "operation", "status"}
            }
            self.db.execute(
                "INSERT INTO provider_events(id,campaign_id,provider,operation,status,details_json,created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    uid(),
                    campaign_id,
                    event.get("provider", "unknown"),
                    event.get("operation", "unknown"),
                    event.get("status", "unknown"),
                    dump(details),
                    now(),
                ),
            )
        if hasattr(provider, "last_events"):
            provider.last_events = []

    def validate_campaign(self, campaign_id: str, job_id: str) -> dict[str, Any]:
        campaign = self._campaign(campaign_id)
        sources = self.db.all("SELECT * FROM approved_sources WHERE campaign_id=?", (campaign_id,))
        if not sources:
            raise ValueError("campaign needs at least one approved source")
        duplicates = len(sources) != len({row["canonical_url"] for row in sources})
        if duplicates:
            raise ValueError("duplicate approved source")
        return {"campaign": campaign["id"], "approved_sources": len(sources), "validated": True}

    def resolve_sources(self, campaign_id: str, job_id: str) -> dict[str, Any]:
        sources = self.db.all("SELECT * FROM approved_sources WHERE campaign_id=?", (campaign_id,))
        failures = 0
        for source in sources:
            try:
                if source["source_type"] == "uploaded":
                    imported = self.db.one(
                        "SELECT * FROM source_imports WHERE approved_source_id=?", (source["id"],)
                    )
                    if not imported:
                        raise ValueError("uploaded approved source is missing its import record")
                    source_metadata = load(source["metadata_json"], {})
                    probe = source_metadata.get("probe", {})
                    resolved_items = [
                        {
                            "external_id": imported["media_sha256"],
                            "source_url": source["url"],
                            "title": source["title"] or imported["original_filename"],
                            "duration_ms": probe.get("duration_ms", 0),
                            "channel": "authorised_upload",
                            "metadata": {
                                "provider": "authorised_upload",
                                "asset_uri": imported["media_uri"],
                                "media_sha256": imported["media_sha256"],
                                "probe": probe,
                                "rights_attested_at": imported["rights_attested_at"],
                            },
                        }
                    ]
                else:
                    resolved_items = self.providers.source.resolve(
                        source["source_type"], source["url"], source["title"]
                    )
                    linked_media = {
                        row["external_id"]: row
                        for row in self.db.all(
                            "SELECT * FROM linked_source_media WHERE approved_source_id=?",
                            (source["id"],),
                        )
                    }
                    for item in resolved_items:
                        linked = linked_media.get(item["external_id"])
                        if linked:
                            item["metadata"].update(
                                {
                                    "asset_uri": linked["media_uri"],
                                    "media_sha256": linked["media_sha256"],
                                    "linked_media_id": linked["id"],
                                    "rights_attested_at": linked["rights_attested_at"],
                                }
                            )
            except Exception as exc:
                failures += 1
                metadata = load(source["metadata_json"], {})
                metadata["resolution_error"] = {
                    "type": type(exc).__name__,
                    "message": redact_secrets(str(exc)),
                }
                self.db.execute(
                    "UPDATE approved_sources SET status='resolution_failed',metadata_json=? WHERE id=?",
                    (dump(metadata), source["id"]),
                )
                continue
            for item in resolved_items:
                existing = self.db.one(
                    "SELECT id FROM source_items WHERE campaign_id=? AND external_id=?",
                    (campaign_id, item["external_id"]),
                )
                if existing:
                    continue
                self.db.execute(
                    "INSERT INTO source_items(id,approved_source_id,campaign_id,external_id,"
                    "source_url,title,duration_ms,channel,published_at,metadata_json) VALUES (?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT DO NOTHING",
                    (
                        uid(),
                        source["id"],
                        campaign_id,
                        item["external_id"],
                        item["source_url"],
                        item["title"],
                        item["duration_ms"],
                        item.get("channel"),
                        item.get("published_at"),
                        dump(item.get("metadata", {})),
                    ),
                )
            self.db.execute(
                "UPDATE approved_sources SET status='resolved' WHERE id=?", (source["id"],)
            )
        self._record_provider_events(campaign_id, self.providers.source)
        count = self.db.one(
            "SELECT COUNT(*) AS n FROM source_items WHERE campaign_id=?", (campaign_id,)
        )["n"]
        if count == 0:
            raise ValueError("no approved source could be resolved")
        return {
            "source_items": count,
            "approved_sources": len(sources),
            "failed_sources": failures,
        }

    def ingest_sources(self, campaign_id: str, job_id: str) -> dict[str, Any]:
        campaign = self._campaign(campaign_id)
        seeds = load(campaign["research_seeds_json"], [])
        items = self.db.all("SELECT * FROM source_items WHERE campaign_id=?", (campaign_id,))
        transcript_failed_items: set[str] = set()
        for item in items:
            metadata = load(item["metadata_json"], {})
            if metadata.get("provider") == "authorised_upload":
                imported = self.db.one(
                    "SELECT i.transcript_json FROM source_imports i "
                    "JOIN source_items s ON s.approved_source_id=i.approved_source_id WHERE s.id=?",
                    (item["id"],),
                )
                segments = load(imported["transcript_json"], []) if imported else []
            elif metadata.get("linked_media_id"):
                imported = self.db.one(
                    "SELECT transcript_json FROM linked_source_media WHERE id=?",
                    (metadata["linked_media_id"],),
                )
                segments = load(imported["transcript_json"], []) if imported else []
            else:
                try:
                    segments = self.providers.source.transcript(item, seeds)
                except Exception as exc:
                    transcript_failed_items.add(item["id"])
                    metadata["transcript_error"] = {
                        "type": type(exc).__name__,
                        "message": redact_secrets(str(exc)),
                    }
                    self.db.execute(
                        "UPDATE source_items SET metadata_json=? WHERE id=?",
                        (dump(metadata), item["id"]),
                    )
                    segments = []
            for segment in segments:
                self.db.execute(
                    "INSERT INTO transcript_segments(id,source_item_id,start_ms,end_ms,text,embedding_json) "
                    "VALUES (?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                    (
                        uid(),
                        item["id"],
                        segment["start_ms"],
                        segment["end_ms"],
                        segment["text"],
                        dump(embedding(segment["text"])),
                    ),
                )
            if not segments:
                transcript_failed_items.add(item["id"])
                metadata["transcript_status"] = "unavailable_requires_authorised_caption_or_media"
                self.db.execute(
                    "UPDATE source_items SET metadata_json=? WHERE id=?",
                    (dump(metadata), item["id"]),
                )
        self._record_provider_events(campaign_id, self.providers.source)
        total = self.db.one(
            "SELECT COUNT(*) AS n FROM transcript_segments t JOIN source_items s ON s.id=t.source_item_id "
            "WHERE s.campaign_id=?",
            (campaign_id,),
        )["n"]
        return {
            "transcript_segments": total,
            "indexed_source_items": len(items) - len(transcript_failed_items),
            "transcript_unavailable": len(transcript_failed_items),
        }

    def analyse_successful_examples(self, campaign_id: str, job_id: str) -> dict[str, Any]:
        examples = self.db.all(
            "SELECT * FROM successful_examples WHERE campaign_id=?", (campaign_id,)
        )
        analysed = []
        live_evidence: list[dict[str, Any]] = []
        inspector = getattr(self.providers.research, "inspect_examples", None)
        if callable(inspector):
            live_evidence = inspector(examples)
            self._record_provider_events(campaign_id, self.providers.research)
        for index, example in enumerate(examples):
            evidence = next(
                (
                    row
                    for row in live_evidence
                    if row["url"] == example["url"]
                    or (
                        row["platform"] == "youtube"
                        and row["url"].split("v=")[-1] in example["url"]
                    )
                ),
                None,
            )
            enriched = {**example, "live_evidence": evidence}
            analysis = self.providers.ai.analyse_example(enriched, index)
            if evidence:
                analysis["live_evidence"] = evidence["raw"]
            analysis["enrichment_features"] = analyse_enrichment_features(analysis)
            self.db.execute(
                "UPDATE successful_examples SET transcript=?,analysis_json=? WHERE id=?",
                (
                    evidence["transcript"]
                    if evidence
                    else "Live metadata unavailable; analysis remains heuristic.",
                    dump(analysis),
                    example["id"],
                ),
            )
            analysed.append({"id": example["id"], "analysis": analysis})
        profile = infer_style(analysed)
        existing = self.db.one(
            "SELECT id FROM style_profiles WHERE campaign_id=? ORDER BY created_at LIMIT 1",
            (campaign_id,),
        )
        if existing:
            profile_id = existing["id"]
            self.db.execute(
                "UPDATE style_profiles SET evidence_count=?,features_json=?,confidence=?,provenance_json=? WHERE id=?",
                (
                    len(examples),
                    dump(profile["features"]),
                    profile["confidence"],
                    dump([row["id"] for row in analysed]),
                    profile_id,
                ),
            )
        else:
            profile_id = uid()
            self.db.execute(
                "INSERT INTO style_profiles(id,campaign_id,name,evidence_count,features_json,confidence,provenance_json,created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    profile_id,
                    campaign_id,
                    "Campaign successful-example profile",
                    len(examples),
                    dump(profile["features"]),
                    profile["confidence"],
                    dump([row["id"] for row in analysed]),
                    now(),
                ),
            )
        return {
            "examples_analysed": len(examples),
            "style_profile_id": profile_id,
            "confidence": profile["confidence"],
        }

    def social_research(self, campaign_id: str, job_id: str) -> dict[str, Any]:
        campaign = self._campaign(campaign_id)
        seeds = load(campaign["research_seeds_json"], [])
        examples = self.db.all(
            "SELECT url,platform,creator,analysis_json FROM successful_examples WHERE campaign_id=?",
            (campaign_id,),
        )
        queries = self.providers.ai.generate_research_queries(campaign, seeds, examples)
        for query in queries:
            self.db.execute(
                "INSERT INTO research_targets(id,campaign_id,target_type,value) VALUES (?,?,?,?) "
                "ON CONFLICT DO NOTHING",
                (uid(), campaign_id, "generated_query", query),
            )
        raw = self.providers.research.collect(campaign, seeds, queries, examples)
        self._record_provider_events(campaign_id, self.providers.research)
        imported = self.db.all(
            "SELECT * FROM research_imports WHERE campaign_id=? ORDER BY imported_at",
            (campaign_id,),
        )
        raw.extend(
            {
                "platform": row["platform"],
                "url": row["url"],
                "creator": row["creator"],
                "published_hours_ago": row["published_hours_ago"],
                "metrics": load(row["metrics_json"], {}),
                "baseline": load(row["baseline_json"], {}),
                "transcript": row["transcript"],
                "labels": load(row["labels_json"], {}),
                "raw": {
                    "research_import_id": row["id"],
                    "provenance": row["provenance"],
                    "original": load(row["raw_json"], {}),
                },
            }
            for row in imported
        )
        observations = []
        for item in raw:
            observation_id = uid()
            derived = research_signals(
                item["metrics"], item["baseline"], item["published_hours_ago"]
            )
            self.db.execute(
                "INSERT INTO research_observations(id,campaign_id,platform,url,creator,observed_at,published_at,"
                "metrics_json,baseline_json,raw_json,derived_json,transcript,labels_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT DO NOTHING",
                (
                    observation_id,
                    campaign_id,
                    item["platform"],
                    item["url"],
                    item["creator"],
                    now(),
                    now(),
                    dump(item["metrics"]),
                    dump(item["baseline"]),
                    dump(item["raw"]),
                    dump(derived),
                    item["transcript"],
                    dump(item["labels"]),
                ),
            )
            stored = self.db.one(
                "SELECT * FROM research_observations WHERE campaign_id=? AND url=?",
                (campaign_id, item["url"]),
            )
            observations.append(
                {
                    "id": stored["id"],
                    "platform": item["platform"],
                    "creator": item["creator"],
                    "labels": item["labels"],
                    "derived": derived,
                }
            )
        clusters = cluster_observations(observations)
        for cluster in clusters:
            self.db.execute(
                "INSERT INTO trend_clusters(id,campaign_id,label,metrics_json,lifecycle_state,evidence_ids_json) "
                "VALUES (?,?,?,?,?,?) ON CONFLICT(campaign_id,label) DO UPDATE SET "
                "metrics_json=excluded.metrics_json,lifecycle_state=excluded.lifecycle_state,"
                "evidence_ids_json=excluded.evidence_ids_json",
                (
                    uid(),
                    campaign_id,
                    cluster["label"],
                    dump(cluster["metrics"]),
                    cluster["lifecycle_state"],
                    dump(cluster["evidence_ids"]),
                ),
            )
        profile_count = 0
        creators = {(row["platform"], row["creator"]) for row in observations}
        for platform, creator in creators:
            members = [
                row
                for row in observations
                if row["platform"] == platform and row["creator"] == creator
            ]
            average_outlier = sum(row["derived"]["relative_outlier"] for row in members) / len(
                members
            )
            profile_metrics = {
                "observation_count": len(members),
                "average_relative_outlier": round(average_outlier, 4),
                "average_view_velocity": round(
                    sum(row["derived"]["view_velocity"] for row in members) / len(members),
                    4,
                ),
                "angles": sorted({row["labels"]["angle"] for row in members}),
                "topics": sorted({row["labels"]["topic"] for row in members}),
            }
            self.db.execute(
                "INSERT INTO creator_profiles(id,campaign_id,platform,creator,metrics_json,"
                "evidence_ids_json,successful_clipper,created_at) VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(campaign_id,platform,creator) DO UPDATE SET "
                "metrics_json=excluded.metrics_json,evidence_ids_json=excluded.evidence_ids_json,"
                "successful_clipper=excluded.successful_clipper,created_at=excluded.created_at",
                (
                    uid(),
                    campaign_id,
                    platform,
                    creator,
                    dump(profile_metrics),
                    dump([row["id"] for row in members]),
                    int(average_outlier >= 5),
                    now(),
                ),
            )
            profile_count += 1
        outliers = sum(1 for row in observations if row["derived"]["relative_outlier"] >= 5)
        return {
            "observations": len(observations),
            "outliers": outliers,
            "clusters": len(clusters),
            "generated_queries": len(queries),
            "creator_profiles": profile_count,
            "manual_imports": len(imported),
            "evidence_separated": True,
        }

    def synthesize_strategy(self, campaign_id: str, job_id: str) -> dict[str, Any]:
        clusters = self.db.all("SELECT * FROM trend_clusters WHERE campaign_id=?", (campaign_id,))
        profile = self.db.one(
            "SELECT * FROM style_profiles WHERE campaign_id=? ORDER BY created_at LIMIT 1",
            (campaign_id,),
        )
        ranked = sorted(
            clusters,
            key=lambda row: load(row["metrics_json"])["avg_relative_outlier"],
            reverse=True,
        )
        evidence = [e for cluster in ranked for e in load(cluster["evidence_ids_json"], [])]
        brief = {
            "ranked_opportunities": [
                {
                    "label": row["label"],
                    "lifecycle": row["lifecycle_state"],
                    "metrics": load(row["metrics_json"]),
                }
                for row in ranked
            ],
            "style_profile_id": profile["id"] if profile else None,
            "recommendation": "Lead with a surprising claim, prove it quickly, and end on a practical payoff.",
            "uncertainty": [
                "Fixture research must be replaced or manually imported for live decisions."
            ],
        }
        existing = self.db.one("SELECT id FROM strategy_briefs WHERE campaign_id=?", (campaign_id,))
        if existing:
            brief_id = existing["id"]
            self.db.execute(
                "UPDATE strategy_briefs SET brief_json=?,evidence_ids_json=?,created_at=? WHERE id=?",
                (dump(brief), dump(evidence), now(), brief_id),
            )
        else:
            brief_id = uid()
            self.db.execute(
                "INSERT INTO strategy_briefs(id,campaign_id,brief_json,evidence_ids_json,created_at) VALUES (?,?,?,?,?)",
                (brief_id, campaign_id, dump(brief), dump(evidence), now()),
            )
        return {
            "strategy_brief_id": brief_id,
            "evidence_count": len(evidence),
            "opportunities": len(ranked),
        }

    def discover_candidates(self, campaign_id: str, job_id: str) -> dict[str, Any]:
        clusters = self.db.all(
            "SELECT * FROM trend_clusters WHERE campaign_id=? ORDER BY lifecycle_state",
            (campaign_id,),
        )
        query_text = " ".join(row["label"] for row in clusters[:3]) or "surprising useful insight"
        query_vector = embedding(query_text)
        evidence_ids = [e for row in clusters for e in load(row["evidence_ids_json"], [])]
        example_count = self.db.one(
            "SELECT COUNT(*) AS n FROM successful_examples WHERE campaign_id=?", (campaign_id,)
        )["n"]
        items = self.db.all(
            "SELECT * FROM source_items WHERE campaign_id=? ORDER BY id", (campaign_id,)
        )
        policy = self.db.one(
            "SELECT * FROM strategy_policies WHERE active=1 ORDER BY version DESC LIMIT 1"
        )
        experiment = self.db.one(
            "SELECT * FROM experiments WHERE status IN ('planned','running') "
            "ORDER BY created_at DESC LIMIT 1"
        )
        treatment_policy = (
            self.db.one(
                "SELECT * FROM strategy_policies WHERE id=?",
                (experiment["treatment_policy_id"],),
            )
            if experiment
            else None
        )
        control_policy = (
            self.db.one(
                "SELECT * FROM strategy_policies WHERE id=?",
                (experiment["control_policy_id"],),
            )
            if experiment
            else policy
        )
        skipped_without_transcript = 0
        for source_index, item in enumerate(items):
            segments = self.db.all(
                "SELECT * FROM transcript_segments WHERE source_item_id=? ORDER BY start_ms",
                (item["id"],),
            )
            if not segments:
                skipped_without_transcript += 1
                continue
            for pass_name, segment in (
                (
                    "research_matched",
                    max(segments, key=lambda s: cosine(load(s["embedding_json"]), query_vector)),
                ),
                ("independently_interesting", segments[-1]),
            ):
                similarity = max(0.0, cosine(load(segment["embedding_json"]), query_vector))
                saturation = 0.15 if pass_name == "independently_interesting" else 0.25
                assignment_key = (
                    f"{experiment['id']}:{item['id']}:{segment['start_ms']}:{pass_name}"
                    if experiment
                    else ""
                )
                bucket = (
                    int(hashlib.sha256(assignment_key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
                    if experiment
                    else 1.0
                )
                arm = (
                    "treatment"
                    if experiment and bucket < float(experiment["allocation"])
                    else "control"
                )
                applied_policy = treatment_policy if arm == "treatment" else control_policy
                weights = load(applied_policy["weights_json"])
                scores = candidate_scores(
                    segment["text"], similarity, example_count, source_index, saturation
                )
                predicted = weighted_score(scores, weights)
                candidate_id = uid()
                self.db.execute(
                    "INSERT INTO candidate_moments(id,campaign_id,source_item_id,start_ms,end_ms,transcript,"
                    "discovery_pass,research_match_json,evidence_ids_json,scores_json,selection_reason,saturation_json,"
                    "predicted_score,policy_id,status,enrichment_suitability_json) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT DO NOTHING",
                    (
                        candidate_id,
                        campaign_id,
                        item["id"],
                        segment["start_ms"],
                        segment["end_ms"],
                        segment["text"],
                        pass_name,
                        dump({"query": query_text, "similarity": round(similarity, 4)}),
                        dump(evidence_ids),
                        dump(scores),
                        f"{pass_name.replace('_', ' ').title()} from approved source; strong hook and evidence alignment.",
                        dump(
                            {
                                "score": saturation,
                                "method": "topic-frequency proxy",
                            }
                        ),
                        predicted,
                        applied_policy["id"],
                        "discovered",
                        dump(enrichment_suitability(segment["text"])),
                    ),
                )
                stored_candidate = self.db.one(
                    "SELECT id FROM candidate_moments WHERE campaign_id=? AND source_item_id=? "
                    "AND start_ms=? AND end_ms=? AND discovery_pass=?",
                    (
                        campaign_id,
                        item["id"],
                        segment["start_ms"],
                        segment["end_ms"],
                        pass_name,
                    ),
                )
                if experiment and stored_candidate:
                    self.db.execute(
                        "INSERT INTO experiment_assignments(id,experiment_id,candidate_id,arm,policy_id,assigned_at) "
                        "VALUES (?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                        (
                            uid(),
                            experiment["id"],
                            stored_candidate["id"],
                            arm,
                            applied_policy["id"],
                            now(),
                        ),
                    )
        if experiment:
            self.db.execute(
                "UPDATE experiments SET status='running' WHERE id=? AND status='planned'",
                (experiment["id"],),
            )
        count = self.db.one(
            "SELECT COUNT(*) AS n FROM candidate_moments WHERE campaign_id=?", (campaign_id,)
        )["n"]
        return {
            "candidates": count,
            "source_items_searched": len(items) - skipped_without_transcript,
            "source_items_without_transcript": skipped_without_transcript,
            "passes": 2,
        }

    def rank_candidates(self, campaign_id: str, job_id: str) -> dict[str, Any]:
        candidates = self.db.all(
            "SELECT * FROM candidate_moments WHERE campaign_id=? ORDER BY predicted_score DESC",
            (campaign_id,),
        )
        if self.settings.provider_mode == "live":
            candidates.sort(
                key=lambda candidate: bool(
                    load(
                        self.db.one(
                            "SELECT metadata_json FROM source_items WHERE id=?",
                            (candidate["source_item_id"],),
                        )["metadata_json"],
                        {},
                    ).get("asset_uri")
                ),
                reverse=True,
            )
        selected_ids = {candidate["id"] for candidate in candidates[:3]}
        if len(candidates) > 3:
            # Preserve one distinct creative opportunity instead of selecting three
            # near-identical top-score moments.
            diverse = max(
                candidates[2:],
                key=lambda row: (
                    float(load(row["scores_json"], {}).get("humour", 0)),
                    float(row["predicted_score"]),
                ),
            )
            selected_ids.discard(candidates[2]["id"])
            selected_ids.add(diverse["id"])
        for candidate in candidates:
            self.db.execute(
                "UPDATE candidate_moments SET status=? WHERE id=?",
                ("selected" if candidate["id"] in selected_ids else "ranked", candidate["id"]),
            )
        if not candidates:
            raise ValueError("no candidate moments discovered")
        winner = candidates[0]
        return {
            "ranked": len(candidates),
            "winner_id": winner["id"],
            "winner_score": winner["predicted_score"],
            "explanation": {
                "winner": load(winner["scores_json"]),
                "runner_up": load(candidates[1]["scores_json"]) if len(candidates) > 1 else None,
            },
        }

    def _eligible_assets(self, campaign_id: str, controls: dict[str, Any]) -> list[dict[str, Any]]:
        prohibited = set(controls.get("prohibited_asset_types", []))
        required_source = str(controls.get("required_asset_source") or "").lower().strip()
        assets = []
        for row in self.db.all(
            "SELECT * FROM assets WHERE (campaign_id=? OR campaign_id IS NULL) "
            "AND permitted_commercial_use=1 ORDER BY created_at",
            (campaign_id,),
        ):
            if row["asset_type"] in prohibited or not self.providers.storage.exists(
                row["file_uri"]
            ):
                continue
            restrictions = load(row["campaign_restrictions_json"], {})
            if campaign_id in restrictions.get("prohibited_campaign_ids", []):
                continue
            allowed_campaigns = restrictions.get("campaign_ids", [])
            if allowed_campaigns and campaign_id not in allowed_campaigns:
                continue
            source_haystack = " ".join(
                [
                    row["licence"],
                    row.get("source_url") or "",
                    load(row["metadata_json"], {}).get("library", ""),
                ]
            ).lower()
            if required_source and required_source not in source_haystack:
                continue
            row["tags"] = load(row["tags_json"], [])
            row["embedding"] = load(row["embedding_json"], [])
            row["metadata"] = load(row["metadata_json"], {})
            row["campaign_restrictions"] = restrictions
            assets.append(row)
        return assets

    @staticmethod
    def _asset_allowed(asset: dict[str, Any], controls: dict[str, Any]) -> bool:
        asset_type = asset["asset_type"]
        media_kind = asset.get("metadata", {}).get("probe", {}).get("media_kind")
        if asset_type == "music":
            return bool(controls.get("music_allowed"))
        if asset_type == "sfx":
            return bool(controls.get("sound_effects_allowed"))
        if asset_type == "broll":
            return bool(controls.get("broll_allowed")) and (
                bool(controls.get("external_video_allowed"))
                if media_kind == "video"
                else bool(controls.get("external_images_allowed"))
            )
        if asset_type in {"meme_image", "meme_video", "reaction"}:
            return bool(controls.get("memes_allowed")) and (
                bool(controls.get("external_video_allowed"))
                if media_kind == "video" or asset_type == "meme_video"
                else bool(controls.get("external_images_allowed"))
            )
        if asset_type in {"image", "graphic"}:
            return bool(controls.get("external_images_allowed"))
        return False

    def _select_asset(
        self,
        assets: list[dict[str, Any]],
        asset_types: set[str],
        text: str,
        controls: dict[str, Any],
        used: set[str],
    ) -> dict[str, Any] | None:
        query = embedding(text)
        choices = [
            asset
            for asset in assets
            if asset["asset_type"] in asset_types
            and asset["id"] not in used
            and self._asset_allowed(asset, controls)
        ]
        return max(choices, key=lambda asset: cosine(asset["embedding"], query), default=None)

    def _event_from_asset(
        self,
        asset: dict[str, Any],
        start_ms: int,
        duration_ms: int,
        mode: str,
        purpose: str,
        reason: str,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "id": stable_id(f"{asset['id']}:{start_ms}:{purpose}", 20),
            "type": asset["asset_type"],
            "asset_id": asset["id"],
            "asset_uri": asset["file_uri"],
            "title": asset["title"],
            "media_kind": asset.get("metadata", {}).get("probe", {}).get("media_kind", "image"),
            "start_ms": start_ms,
            "duration_ms": duration_ms,
            "mode": mode,
            "purpose": purpose,
            "reason": reason,
            "parameters": parameters or {},
            "provenance": {
                "licence": asset["licence"],
                "permitted_commercial_use": bool(asset["permitted_commercial_use"]),
                "attribution_requirement": asset.get("attribution_requirement"),
                "attribution_text": asset.get("attribution_requirement"),
                "source_url": asset.get("source_url"),
                "library": asset.get("metadata", {}).get("library"),
                "campaign_restrictions": asset.get("campaign_restrictions", {}),
                "rights_attestation": asset["rights_attestation"],
            },
            "storage_verified": self.providers.storage.exists(asset["file_uri"]),
        }

    def build_enrichment_plan(
        self, campaign_id: str, candidate: dict[str, Any], version: int = 1
    ) -> dict[str, Any]:
        campaign = self._campaign(campaign_id)
        controls = load(campaign.get("enrichment_config_json"), {})
        defaults = {
            "music_allowed": False,
            "memes_allowed": False,
            "broll_allowed": False,
            "sound_effects_allowed": False,
            "external_images_allowed": False,
            "external_video_allowed": False,
            "prohibited_asset_types": [],
            "max_inserts": 0,
            "max_insert_duration_seconds": 2.0,
            "music_volume_min_db": -30.0,
            "music_volume_max_db": -12.0,
            "ducking_required": True,
            "additional_instructions": "",
        }
        controls = {**defaults, **controls}
        suitability = load(candidate.get("enrichment_suitability_json"), {})
        assets = self._eligible_assets(campaign_id, controls)
        events: list[dict[str, Any]] = []
        used: set[str] = set()
        duration_ms = max(1000, candidate["end_ms"] - candidate["start_ms"])
        max_insert_ms = round(float(controls["max_insert_duration_seconds"]) * 1000)
        max_inserts = int(controls["max_inserts"])

        music_signal = suitability.get("music_suitability", {}).get("value")
        music = self._select_asset(assets, {"music"}, candidate["transcript"], controls, used)
        if music and music_signal is not None and music_signal >= 0.5:
            volume_db = min(-18.0, float(controls["music_volume_max_db"]))
            volume_db = max(volume_db, float(controls["music_volume_min_db"]))
            events.append(
                self._event_from_asset(
                    music,
                    0,
                    duration_ms,
                    "background",
                    "enhance emotional tone without masking speech",
                    "candidate emotional-language signal and campaign-authorised music",
                    {
                        "volume_db": volume_db,
                        "loop": True,
                        "fade_in_ms": min(750, duration_ms // 4),
                        "fade_out_ms": min(750, duration_ms // 4),
                        "ducking": bool(controls["ducking_required"]),
                    },
                )
            )
            used.add(music["id"])

        humour_signal = suitability.get("humour_insert_opportunity", {}).get("value")
        meme = self._select_asset(
            assets,
            {"meme_image", "meme_video", "reaction"},
            candidate["transcript"],
            controls,
            used,
        )
        if meme and max_inserts > 0 and humour_signal is not None and humour_signal >= 0.7:
            start = min(max(500, duration_ms // 3), max(0, duration_ms - 750))
            event_duration = min(
                max_insert_ms, meme.get("duration_ms") or 1200, duration_ms - start
            )
            events.append(
                self._event_from_asset(
                    meme,
                    start,
                    max(250, event_duration),
                    "overlay",
                    "reinforce a humorous or absurd beat",
                    "semantic match to humour language in the timestamped moment",
                )
            )
            used.add(meme["id"])

        context_signal = suitability.get("broll_suitability", {}).get("value")
        broll = self._select_asset(assets, {"broll"}, candidate["transcript"], controls, used)
        external_inserts = sum(event["type"] != "music" for event in events)
        if (
            broll
            and external_inserts < max_inserts
            and context_signal is not None
            and context_signal >= 0.7
        ):
            start = min(max(1000, duration_ms * 2 // 3), max(0, duration_ms - 1000))
            event_duration = min(
                max_insert_ms, broll.get("duration_ms") or 1500, duration_ms - start
            )
            events.append(
                self._event_from_asset(
                    broll,
                    start,
                    max(250, event_duration),
                    "picture_in_picture",
                    "visually illustrate a contextual claim",
                    "semantic match to explanatory language in the timestamped moment",
                )
            )
            used.add(broll["id"])

        sfx = self._select_asset(assets, {"sfx"}, candidate["transcript"], controls, used)
        external_inserts = sum(event["type"] != "music" for event in events)
        if (
            sfx
            and external_inserts < max_inserts
            and humour_signal is not None
            and humour_signal >= 0.7
        ):
            sfx_duration = min(max_insert_ms, sfx.get("duration_ms") or 750, duration_ms)
            events.append(
                self._event_from_asset(
                    sfx,
                    max(0, duration_ms - sfx_duration),
                    sfx_duration,
                    "audio_emphasis",
                    "punctuate the humorous payoff",
                    "humour signal and a semantically matched authorised sound effect",
                    {"volume_db": -10.0},
                )
            )
            used.add(sfx["id"])

        enabled = any(
            controls.get(key)
            for key in (
                "music_allowed",
                "memes_allowed",
                "broll_allowed",
                "sound_effects_allowed",
                "external_images_allowed",
                "external_video_allowed",
            )
        )
        if (
            enabled
            and suitability.get("humour_insert_opportunity", {}).get("status") != "unavailable"
        ):
            events.append(
                {
                    "id": stable_id(f"{candidate['id']}:punch-in:{version}", 20),
                    "type": "punch_in",
                    "start_ms": min(500, max(0, duration_ms - 750)),
                    "duration_ms": min(1000, duration_ms),
                    "mode": "native",
                    "purpose": "emphasise the opening hook",
                    "reason": "native emphasis is rights-safe and the hook is a high-attention moment",
                    "parameters": {"scale": 1.12},
                }
            )

        strategy = self._enrichment_strategy(events, duration_ms)
        return {
            "planner": "local_evidence_enrichment_v1",
            "candidate_id": candidate["id"],
            "version": version,
            "warranted": bool(events),
            "decision_reason": (
                "Campaign permissions, candidate signals and authorised semantic asset matches supported this plan."
                if events
                else "No permitted evidence-backed enrichment was warranted."
            ),
            "controls": controls,
            "suitability": suitability,
            "events": sorted(events, key=lambda event: event["start_ms"]),
            "strategy_features": strategy,
        }

    @staticmethod
    def _enrichment_strategy(events: list[dict[str, Any]], duration_ms: int) -> dict[str, Any]:
        duration_units = max(0.1, duration_ms / 10_000)
        return {
            "music": any(event["type"] == "music" for event in events),
            "meme": any(
                event["type"] in {"meme_image", "meme_video", "reaction"} for event in events
            ),
            "broll_density_per_10s": round(
                sum(event["type"] == "broll" for event in events) / duration_units, 3
            ),
            "zoom_frequency_per_10s": round(
                sum(
                    event["type"] in {"punch_in", "dynamic_crop", "speaker_focus"}
                    for event in events
                )
                / duration_units,
                3,
            ),
            "sfx_frequency_per_10s": round(
                sum(event["type"] == "sfx" for event in events) / duration_units, 3
            ),
            "reaction_insert_timing_ms": [
                int(event.get("start_ms", 0))
                for event in events
                if event.get("type") in {"meme_image", "meme_video", "reaction"}
            ],
        }

    def revise_enrichment_spec(
        self,
        campaign_id: str,
        candidate: dict[str, Any],
        spec: dict[str, Any],
        changes: dict[str, Any],
        version: int,
    ) -> dict[str, Any]:
        """Apply asset-aware review changes while preserving the immutable parent plan."""
        if changes.get("enrichment_regenerate"):
            plan = self.build_enrichment_plan(campaign_id, candidate, version)
            return {**spec, "enrichment": plan}

        plan = spec.setdefault("enrichment", {})
        controls = plan.get("controls", {})
        events = plan.setdefault("events", [])
        assets = self._eligible_assets(campaign_id, controls)
        used = {event.get("asset_id") for event in events if event.get("asset_id")}
        duration_ms = max(1000, int(spec.get("duration_ms", 1000)))

        replace_type = changes.get("enrichment_replace_asset_type")
        if replace_type:
            replace_types = (
                {"meme_image", "meme_video", "reaction"}
                if replace_type == "meme"
                else {replace_type}
            )
            replaced = next((event for event in events if event.get("type") in replace_types), None)
            if replaced:
                used.discard(replaced.get("asset_id"))
                replacement = self._select_asset(
                    assets, replace_types, candidate["transcript"], controls, used
                )
                if replacement:
                    events[events.index(replaced)] = self._event_from_asset(
                        replacement,
                        int(replaced.get("start_ms", 0)),
                        int(replaced.get("duration_ms", duration_ms)),
                        str(replaced.get("mode", "background")),
                        str(replaced.get("purpose", "human-requested replacement")),
                        "replacement requested during human review",
                        replaced.get("parameters", {}),
                    )

        request_type = changes.get("enrichment_request_asset_type")
        external_types = {"broll", "meme_image", "meme_video", "reaction", "image", "graphic"}
        insert_count = sum(event.get("type") in external_types for event in events)
        if request_type and insert_count < int(controls.get("max_inserts", 0)):
            addition = self._select_asset(
                assets, {request_type}, candidate["transcript"], controls, used
            )
            if not addition:
                addition = self._select_asset(
                    assets, {request_type}, candidate["transcript"], controls, set()
                )
            if addition:
                max_duration = round(float(controls.get("max_insert_duration_seconds", 2.0)) * 1000)
                event_duration = min(max_duration, addition.get("duration_ms") or 1500, duration_ms)
                start = max(0, duration_ms - event_duration)
                events.append(
                    self._event_from_asset(
                        addition,
                        start,
                        event_duration,
                        "picture_in_picture",
                        "add visual context",
                        "additional B-roll requested during human review",
                    )
                )

        plan["version"] = version
        plan["events"] = sorted(events, key=lambda event: int(event.get("start_ms", 0)))
        plan["strategy_features"] = self._enrichment_strategy(plan["events"], duration_ms)
        plan["decision_reason"] = "Plan revised from explicit human review instructions."
        spec.setdefault("metadata", {})["enrichment_strategy"] = plan["strategy_features"]
        return spec

    def plan_enrichment(self, campaign_id: str, job_id: str) -> dict[str, Any]:
        candidates = self.db.all(
            "SELECT * FROM candidate_moments WHERE campaign_id=? AND status='selected' "
            "ORDER BY predicted_score DESC",
            (campaign_id,),
        )
        event_count = 0
        for candidate in candidates:
            existing = self.db.one(
                "SELECT id,plan_json FROM enrichment_plans WHERE candidate_id=? AND version=1",
                (candidate["id"],),
            )
            if existing:
                event_count += len(load(existing["plan_json"], {}).get("events", []))
                continue
            plan = self.build_enrichment_plan(campaign_id, candidate)
            self.db.execute(
                "INSERT INTO enrichment_plans(id,campaign_id,candidate_id,version,plan_json,"
                "strategy_features_json,created_at) VALUES (?,?,?,?,?,?,?)",
                (
                    uid(),
                    campaign_id,
                    candidate["id"],
                    1,
                    dump(plan),
                    dump(plan["strategy_features"]),
                    now(),
                ),
            )
            event_count += len(plan["events"])
        return {"plans": len(candidates), "events": event_count, "planner": "evidence_driven_v1"}

    def render(self, campaign_id: str, job_id: str) -> dict[str, Any]:
        campaign = self._campaign(campaign_id)
        watermark = load(campaign["watermark_json"], {}) or {}
        style = self.db.one(
            "SELECT id FROM style_profiles WHERE campaign_id=? ORDER BY created_at LIMIT 1",
            (campaign_id,),
        )
        candidates = self.db.all(
            "SELECT * FROM candidate_moments WHERE campaign_id=? AND status='selected' ORDER BY predicted_score DESC",
            (campaign_id,),
        )
        rendered = 0
        for candidate in candidates:
            existing = self.db.one(
                "SELECT id FROM clip_variants WHERE candidate_id=? AND version=1",
                (candidate["id"],),
            )
            if existing:
                rendered += 1
                continue
            # A killed worker retries the same object key instead of leaking duplicate renders.
            variant_id = stable_id(f"{candidate['id']}:variant:1", 32)
            source_item = self.db.one(
                "SELECT * FROM source_items WHERE id=? AND campaign_id=?",
                (candidate["source_item_id"], campaign_id),
            )
            source_metadata = load(source_item["metadata_json"], {})
            if self.settings.provider_mode == "live" and not source_metadata.get("asset_uri"):
                self.db.execute(
                    "UPDATE candidate_moments SET status='render_blocked_missing_authorised_media' WHERE id=?",
                    (candidate["id"],),
                )
                continue
            plan_row = self.db.one(
                "SELECT * FROM enrichment_plans WHERE candidate_id=? AND version=1",
                (candidate["id"],),
            )
            if plan_row:
                enrichment_plan = load(plan_row["plan_json"], {})
                enrichment_plan_id = plan_row["id"]
            else:
                enrichment_plan = self.build_enrichment_plan(campaign_id, candidate)
                enrichment_plan_id = uid()
                self.db.execute(
                    "INSERT INTO enrichment_plans(id,campaign_id,candidate_id,version,plan_json,"
                    "strategy_features_json,created_at) VALUES (?,?,?,?,?,?,?)",
                    (
                        enrichment_plan_id,
                        campaign_id,
                        candidate["id"],
                        1,
                        dump(enrichment_plan),
                        dump(enrichment_plan["strategy_features"]),
                        now(),
                    ),
                )
            spec = {
                "source_item_id": candidate["source_item_id"],
                "source_asset_uri": source_metadata.get("asset_uri"),
                "source_probe": source_metadata.get("probe", {}),
                "start_ms": candidate["start_ms"],
                "end_ms": candidate["end_ms"],
                "duration_ms": candidate["end_ms"] - candidate["start_ms"],
                "aspect_ratio": "9:16",
                "width": 720,
                "height": 1280,
                "captions": {"enabled": True, "size": "medium", "text": candidate["transcript"]},
                "watermark": {
                    "enabled": bool(watermark),
                    "position": watermark.get("position", "bottom_right"),
                    "opacity": watermark.get("opacity", 0.85),
                    "padding": watermark.get("padding", 24),
                    "size_pct": watermark.get("size_pct", 0.18),
                    "asset_uri": watermark.get("asset_uri"),
                },
                "headline": {"enabled": False, "text": ""},
                "crop": {"mode": "center", "adjustment": "center"},
                "audio": {"normalise": True},
                "enrichment": {**enrichment_plan, "plan_id": enrichment_plan_id},
                "metadata": {
                    "campaign_id": campaign_id,
                    "enrichment_strategy": enrichment_plan["strategy_features"],
                },
            }
            result = self.providers.renderer.render(campaign_id, variant_id, spec)
            spec["render"] = {
                "renderer": result.renderer,
                "sha256": result.sha256,
                "probe": result.probe,
                "file_uri": result.file_uri,
                "storage_verified": self.providers.storage.exists(result.file_uri),
            }
            self.db.execute(
                "INSERT INTO clip_variants(id,candidate_id,parent_id,style_profile_id,version,render_spec_json,file_uri,"
                "qa_status,deterministic_qa_json,ai_qa_json,predicted_score,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    variant_id,
                    candidate["id"],
                    None,
                    style["id"] if style else None,
                    1,
                    dump(spec),
                    result.file_uri,
                    "pending",
                    "{}",
                    "{}",
                    candidate["predicted_score"],
                    now(),
                ),
            )
            rendered += 1
        if self.settings.provider_mode == "live" and rendered == 0:
            raise ValueError(
                "selected moments need rights-attested source media linked by YouTube video id before rendering"
            )
        return {"rendered_variants": rendered, "renderer": "ffmpeg_with_manifest_fallback"}

    def qa(self, campaign_id: str, job_id: str) -> dict[str, Any]:
        requirements = self._requirements(campaign_id)
        approved_items = {
            row["id"]
            for row in self.db.all(
                "SELECT id FROM source_items WHERE campaign_id=?", (campaign_id,)
            )
        }
        variants = self.db.all(
            "SELECT v.* FROM clip_variants v JOIN candidate_moments c ON c.id=v.candidate_id WHERE c.campaign_id=?",
            (campaign_id,),
        )
        passed = 0
        for variant in variants:
            spec = load(variant["render_spec_json"])
            report = deterministic_qa(spec, requirements, approved_items)
            ai_requirements = [r for r in requirements if r["requirement_type"] == "ai_evaluated"]
            ai_report = self.providers.ai.evaluate_soft_requirements(spec, ai_requirements)
            status = "passed" if report["passed"] else "failed"
            self.db.execute(
                "UPDATE clip_variants SET qa_status=?,deterministic_qa_json=?,ai_qa_json=? WHERE id=?",
                (status, dump(report), dump(ai_report), variant["id"]),
            )
            passed += report["passed"]
        return {
            "variants": len(variants),
            "passed": passed,
            "failed": len(variants) - passed,
            "ai_checks_separate": True,
        }

    def review_ready(self, campaign_id: str, job_id: str) -> dict[str, Any]:
        campaign = self._campaign(campaign_id)
        variants = self.db.one(
            "SELECT COUNT(*) AS n FROM clip_variants v JOIN candidate_moments c ON c.id=v.candidate_id WHERE c.campaign_id=?",
            (campaign_id,),
        )["n"]
        sources = self.db.one(
            "SELECT COUNT(*) AS n FROM source_items WHERE campaign_id=?", (campaign_id,)
        )["n"]
        candidates = self.db.one(
            "SELECT COUNT(*) AS n FROM candidate_moments WHERE campaign_id=?", (campaign_id,)
        )["n"]
        strategy = self.db.one(
            "SELECT brief_json FROM strategy_briefs WHERE campaign_id=?", (campaign_id,)
        )
        strategy_brief = load(strategy["brief_json"], {}) if strategy else {}
        opportunity_labels = [
            row.get("label", "")
            for row in strategy_brief.get("ranked_opportunities", [])[:3]
            if row.get("label")
        ]
        research_summary = strategy_brief.get(
            "recommendation", "Research completed; inspect the evidence in the review dashboard."
        )
        if opportunity_labels:
            research_summary += f" Top opportunities: {', '.join(opportunity_labels)}."
        key = f"review-ready:{campaign_id}:{job_id}"
        existing = self.db.one("SELECT * FROM notifications WHERE idempotency_key=?", (key,))
        if not existing:
            body = "\n".join(
                [
                    f"Campaign: {campaign['name']}",
                    f"Sources analysed: {sources}",
                    f"Research summary: {research_summary}",
                    f"Candidates considered: {candidates}",
                    f"Clips produced: {variants}",
                    f"Review: {self.settings.base_url}/?campaign={campaign_id}",
                ]
            )
            uri = self.providers.email.send(
                campaign["owner_email"], f"{campaign['name']} is ready for review", body, key
            )
            self.db.execute(
                "INSERT INTO notifications(id,campaign_id,notification_type,idempotency_key,recipient,file_uri,created_at) VALUES (?,?,?,?,?,?,?)",
                (uid(), campaign_id, "review_ready", key, campaign["owner_email"], uri, now()),
            )
        self.db.execute(
            "UPDATE campaigns SET status='awaiting_review',updated_at=? WHERE id=?",
            (now(), campaign_id),
        )
        self.db.execute(
            "INSERT INTO research_ledger(id,campaign_id,entry_type,finding,evidence_json,confidence,decision,applies_to_json,policy_id,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                uid(),
                campaign_id,
                "recommendation",
                "Research-aligned candidates were rendered for human review.",
                dump({"job_id": job_id, "variant_count": variants}),
                0.65,
                "await_human_review",
                dump({"campaign_id": campaign_id}),
                self.ensure_default_policy(),
                now(),
            ),
        )
        return {"review_ready": True, "variants": variants, "notification_idempotency_key": key}

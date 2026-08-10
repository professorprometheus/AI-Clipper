from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .config import Settings
from .db import Database, dump, load, now, uid
from .domain import (
    DEFAULT_WEIGHTS,
    candidate_scores,
    cluster_observations,
    cosine,
    deterministic_qa,
    embedding,
    infer_style,
    research_signals,
    weighted_score,
)
from .providers import (
    EmailAdapter,
    FileEmailAdapter,
    FixtureResearchProvider,
    FixtureSourceProvider,
    LocalStorageAdapter,
    ManualExportAdapter,
    ManualImportSourceProvider,
    PublicationAdapter,
    Renderer,
    ResearchProvider,
    SourceProvider,
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
    "render",
    "qa",
    "review_ready",
]


@dataclass
class Providers:
    storage: LocalStorageAdapter
    source: SourceProvider
    research: ResearchProvider
    email: EmailAdapter
    publication: PublicationAdapter
    renderer: Renderer

    @classmethod
    def build(cls, settings: Settings) -> Providers:
        storage = LocalStorageAdapter(settings.storage_path)
        source: SourceProvider = (
            FixtureSourceProvider()
            if settings.provider_mode == "fixture"
            else ManualImportSourceProvider()
        )
        return cls(
            storage=storage,
            source=source,
            research=FixtureResearchProvider(),
            email=FileEmailAdapter(settings.email_sink_path),
            publication=ManualExportAdapter(storage),
            renderer=Renderer(storage),
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
            "idempotency_key,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
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
            ),
        )
        self.db.execute(
            "UPDATE campaigns SET status='processing',updated_at=? WHERE id=?", (now(), campaign_id)
        )
        self.db.audit("campaign", campaign_id, "pipeline_enqueued", {"job_id": job_id})
        return self.db.one("SELECT * FROM pipeline_jobs WHERE id=?", (job_id,)) or {}

    def acquire(self, worker_token: str) -> dict[str, Any] | None:
        timestamp = now()
        lease = (datetime.now(UTC) + timedelta(seconds=self.settings.lease_seconds)).isoformat()
        with self.db.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM pipeline_jobs WHERE "
                "status IN ('queued','retry') OR (status='leased' AND lease_expires_at < ?) "
                "ORDER BY created_at LIMIT 1",
                (timestamp,),
            ).fetchone()
            if not row:
                return None
            job = dict(row)
            connection.execute(
                "UPDATE pipeline_jobs SET status='leased',worker_token=?,lease_expires_at=?,"
                "heartbeat_at=?,updated_at=? WHERE id=?",
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
            "INSERT OR REPLACE INTO stage_runs(id,job_id,stage,status,attempt,output_json,started_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (stage_run_id, job["id"], stage, "running", job["attempts"] + 1, "{}", started),
        )
        logger.info(dump({"event": "stage_started", "job_id": job["id"], "stage": stage}))
        try:
            output = self.stage_handlers[stage](job["campaign_id"], job["id"])
            checkpoint = load(job["checkpoint_json"], {"completed_stages": []})
            completed = list(dict.fromkeys([*checkpoint.get("completed_stages", []), stage]))
            checkpoint.update({"completed_stages": completed, "last_output": output})
            index = STAGES.index(stage)
            final = index == len(STAGES) - 1
            next_stage = stage if final else STAGES[index + 1]
            status = "awaiting_review" if final else "queued"
            self.db.execute(
                "UPDATE pipeline_jobs SET status=?,current_stage=?,checkpoint_json=?,worker_token=NULL,"
                "lease_expires_at=NULL,error_json=NULL,updated_at=? WHERE id=? AND worker_token=?",
                (status, next_stage, dump(checkpoint), now(), job["id"], worker_token),
            )
            self.db.execute(
                "UPDATE stage_runs SET status='completed',output_json=?,completed_at=? WHERE id=?",
                (dump(output), now(), stage_run_id),
            )
            logger.info(dump({"event": "stage_completed", "job_id": job["id"], "stage": stage}))
            return {"job_id": job["id"], "stage": stage, "status": status, "output": output}
        except Exception as exc:
            attempts = int(job["attempts"]) + 1
            status = "failed" if attempts >= 5 else "retry"
            error = {
                "type": type(exc).__name__,
                "message": str(exc),
                "stage": stage,
                "retryable": status == "retry",
            }
            self.db.execute(
                "UPDATE pipeline_jobs SET status=?,attempts=?,error_json=?,worker_token=NULL,"
                "lease_expires_at=NULL,updated_at=? WHERE id=?",
                (status, attempts, dump(error), now(), job["id"]),
            )
            self.db.execute(
                "UPDATE stage_runs SET status='failed',output_json=?,completed_at=? WHERE id=?",
                (dump(error), now(), stage_run_id),
            )
            logger.exception("stage failed", extra={"job_id": job["id"], "stage": stage})
            return {"job_id": job["id"], "stage": stage, "status": status, "error": error}

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
        count = 0
        for source in sources:
            for item in self.providers.source.resolve(
                source["source_type"], source["url"], source["title"]
            ):
                self.db.execute(
                    "INSERT OR IGNORE INTO source_items(id,approved_source_id,campaign_id,external_id,"
                    "source_url,title,duration_ms,channel,published_at,metadata_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
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
        count = self.db.one(
            "SELECT COUNT(*) AS n FROM source_items WHERE campaign_id=?", (campaign_id,)
        )["n"]
        return {"source_items": count, "approved_sources": len(sources)}

    def ingest_sources(self, campaign_id: str, job_id: str) -> dict[str, Any]:
        campaign = self._campaign(campaign_id)
        seeds = load(campaign["research_seeds_json"], [])
        items = self.db.all("SELECT * FROM source_items WHERE campaign_id=?", (campaign_id,))
        for item in items:
            for segment in self.providers.source.transcript(item, seeds):
                self.db.execute(
                    "INSERT OR IGNORE INTO transcript_segments(id,source_item_id,start_ms,end_ms,text,embedding_json) "
                    "VALUES (?,?,?,?,?,?)",
                    (
                        uid(),
                        item["id"],
                        segment["start_ms"],
                        segment["end_ms"],
                        segment["text"],
                        dump(embedding(segment["text"])),
                    ),
                )
        total = self.db.one(
            "SELECT COUNT(*) AS n FROM transcript_segments t JOIN source_items s ON s.id=t.source_item_id "
            "WHERE s.campaign_id=?",
            (campaign_id,),
        )["n"]
        return {"transcript_segments": total, "indexed_source_items": len(items)}

    def analyse_successful_examples(self, campaign_id: str, job_id: str) -> dict[str, Any]:
        examples = self.db.all(
            "SELECT * FROM successful_examples WHERE campaign_id=?", (campaign_id,)
        )
        analysed = []
        for index, example in enumerate(examples):
            analysis = {
                "hook": "contrarian promise",
                "topic": "campaign-aligned insight",
                "subtopic": "practical proof",
                "emotion": "surprise",
                "controversy": 0.45,
                "humour": 0.25,
                "context": "minimal",
                "structure": ["hook", "proof", "payoff"],
                "duration_seconds": 28 + (index % 3) * 2,
                "opening_type": "direct_claim",
                "headline": "short_bold",
                "caption_pattern": "medium_chunks",
                "crop": "speaker_centered_9_16",
                "pacing": "fast",
                "ending": "payoff",
                "evidence": {"example_id": example["id"], "url": example["url"]},
                "confidence": 0.72,
            }
            self.db.execute(
                "UPDATE successful_examples SET transcript=?,analysis_json=? WHERE id=?",
                (
                    "A supplied successful example with a direct hook, proof and payoff.",
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
        raw = self.providers.research.collect(campaign, seeds)
        observations = []
        for item in raw:
            observation_id = uid()
            derived = research_signals(
                item["metrics"], item["baseline"], item["published_hours_ago"]
            )
            self.db.execute(
                "INSERT OR IGNORE INTO research_observations(id,campaign_id,platform,url,creator,observed_at,published_at,"
                "metrics_json,baseline_json,raw_json,derived_json,transcript,labels_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
                    "creator": item["creator"],
                    "labels": item["labels"],
                    "derived": derived,
                }
            )
        clusters = cluster_observations(observations)
        for cluster in clusters:
            self.db.execute(
                "INSERT OR REPLACE INTO trend_clusters(id,campaign_id,label,metrics_json,lifecycle_state,evidence_ids_json) "
                "VALUES (COALESCE((SELECT id FROM trend_clusters WHERE campaign_id=? AND label=?),?),?,?,?,?,?)",
                (
                    campaign_id,
                    cluster["label"],
                    uid(),
                    campaign_id,
                    cluster["label"],
                    dump(cluster["metrics"]),
                    cluster["lifecycle_state"],
                    dump(cluster["evidence_ids"]),
                ),
            )
        outliers = sum(1 for row in observations if row["derived"]["relative_outlier"] >= 5)
        return {
            "observations": len(observations),
            "outliers": outliers,
            "clusters": len(clusters),
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
        weights = load(policy["weights_json"])
        for source_index, item in enumerate(items):
            segments = self.db.all(
                "SELECT * FROM transcript_segments WHERE source_item_id=? ORDER BY start_ms",
                (item["id"],),
            )
            for pass_name, segment in (
                (
                    "research_matched",
                    max(segments, key=lambda s: cosine(load(s["embedding_json"]), query_vector)),
                ),
                ("independently_interesting", segments[-1]),
            ):
                similarity = max(0.0, cosine(load(segment["embedding_json"]), query_vector))
                saturation = 0.15 if pass_name == "independently_interesting" else 0.25
                scores = candidate_scores(
                    segment["text"], similarity, example_count, source_index, saturation
                )
                predicted = weighted_score(scores, weights)
                self.db.execute(
                    "INSERT OR IGNORE INTO candidate_moments(id,campaign_id,source_item_id,start_ms,end_ms,transcript,"
                    "discovery_pass,research_match_json,evidence_ids_json,scores_json,selection_reason,saturation_json,"
                    "predicted_score,policy_id,status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        uid(),
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
                        dump({"score": saturation, "method": "fixture topic-frequency proxy"}),
                        predicted,
                        policy["id"],
                        "discovered",
                    ),
                )
        count = self.db.one(
            "SELECT COUNT(*) AS n FROM candidate_moments WHERE campaign_id=?", (campaign_id,)
        )["n"]
        return {"candidates": count, "source_items_searched": len(items), "passes": 2}

    def rank_candidates(self, campaign_id: str, job_id: str) -> dict[str, Any]:
        candidates = self.db.all(
            "SELECT * FROM candidate_moments WHERE campaign_id=? ORDER BY predicted_score DESC",
            (campaign_id,),
        )
        for index, candidate in enumerate(candidates):
            self.db.execute(
                "UPDATE candidate_moments SET status=? WHERE id=?",
                ("selected" if index < 3 else "ranked", candidate["id"]),
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
            variant_id = uid()
            spec = {
                "source_item_id": candidate["source_item_id"],
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
                "metadata": {"campaign_id": campaign_id},
            }
            result = self.providers.renderer.render(campaign_id, variant_id, spec)
            spec["render"] = {"renderer": result.renderer, "sha256": result.sha256}
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
            ai_report = {
                "label": "ai_evaluated",
                "advisory_only": True,
                "checks": [
                    {"key": row["key"], "result": "uncertain_fixture", "confidence": 0.35}
                    for row in ai_requirements
                ],
            }
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
        key = f"review-ready:{campaign_id}:{job_id}"
        existing = self.db.one("SELECT * FROM notifications WHERE idempotency_key=?", (key,))
        if not existing:
            body = f"ALPHA has {variants} clips ready for review. Review: {self.settings.base_url}/?campaign={campaign_id}"
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

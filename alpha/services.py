from __future__ import annotations

import binascii
from pathlib import Path
from typing import Any

from .db import Database, dump, load, now, uid
from .domain import apply_changes, deterministic_qa, parse_edit_instruction
from .pipeline import Pipeline
from .providers import canonical_url, decode_upload, stable_id
from .schemas import (
    CampaignCreate,
    ExperimentInput,
    FeedbackInput,
    PerformanceInput,
    PublishInput,
    ReviewInput,
)


class AlphaService:
    def __init__(self, db: Database, pipeline: Pipeline):
        self.db = db
        self.pipeline = pipeline

    def create_campaign(self, payload: CampaignCreate) -> dict[str, Any]:
        campaign_id = uid()
        timestamp = now()
        watermark: dict[str, Any] | None = None
        if payload.watermark:
            watermark = payload.watermark.model_dump(exclude={"data_base64"})
            if payload.watermark.data_base64:
                try:
                    content = decode_upload(payload.watermark.data_base64)
                except (ValueError, binascii.Error) as exc:
                    raise ValueError("invalid base64 watermark") from exc
                if len(content) > 5_000_000:
                    raise ValueError("watermark exceeds 5 MB")
                suffix = Path(payload.watermark.filename).suffix.lower()
                if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".ppm"}:
                    raise ValueError("unsupported watermark format")
                watermark["asset_uri"] = self.pipeline.providers.storage.put_bytes(
                    f"watermarks/{campaign_id}/{stable_id(payload.watermark.filename)}{suffix}",
                    content,
                )
        self.db.execute(
            "INSERT INTO campaigns(id,name,owner_email,platform,campaign_url,payout_model,payout_value,currency,"
            "deadline,status,research_seeds_json,target_platforms_json,watermark_json,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                campaign_id,
                payload.name,
                str(payload.owner_email),
                payload.platform,
                str(payload.campaign_url) if payload.campaign_url else None,
                payload.payout_model,
                payload.payout_value,
                payload.currency,
                payload.deadline,
                "draft",
                dump(payload.research_seeds),
                dump(payload.target_platforms),
                dump(watermark) if watermark else None,
                timestamp,
                timestamp,
            ),
        )
        for source in payload.sources:
            self.db.execute(
                "INSERT INTO approved_sources(id,campaign_id,source_type,url,canonical_url,title,status,metadata_json,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    uid(),
                    campaign_id,
                    source.type,
                    str(source.url),
                    canonical_url(str(source.url)),
                    source.title,
                    "pending",
                    "{}",
                    timestamp,
                ),
            )
        for example in payload.successful_examples:
            self.db.execute(
                "INSERT INTO successful_examples(id,campaign_id,url,canonical_url,platform,creator,metrics_json,created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    uid(),
                    campaign_id,
                    str(example.url),
                    canonical_url(str(example.url)),
                    example.platform,
                    example.creator,
                    "{}",
                    timestamp,
                ),
            )
        for requirement in payload.requirements:
            self._insert_requirement(campaign_id, requirement.model_dump(), timestamp)
        for seed in payload.research_seeds:
            self.db.execute(
                "INSERT OR IGNORE INTO research_targets(id,campaign_id,target_type,value) VALUES (?,?,?,?)",
                (uid(), campaign_id, "keyword", seed),
            )
        self.db.audit(
            "campaign",
            campaign_id,
            "created",
            {
                "source_count": len(payload.sources),
                "example_count": len(payload.successful_examples),
            },
        )
        return self.get_campaign(campaign_id)

    def _insert_requirement(
        self, campaign_id: str, requirement: dict[str, Any], timestamp: str | None = None
    ) -> str:
        requirement_id = uid()
        self.db.execute(
            "INSERT INTO campaign_requirements(id,campaign_id,key,requirement_type,operator,value_json,severity,source_text,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                requirement_id,
                campaign_id,
                requirement["key"],
                requirement["type"],
                requirement.get("operator", "eq"),
                dump(requirement.get("value")),
                requirement.get("severity", "mandatory"),
                requirement.get("source_text"),
                timestamp or now(),
            ),
        )
        return requirement_id

    def get_campaign(self, campaign_id: str) -> dict[str, Any]:
        campaign = self.db.one("SELECT * FROM campaigns WHERE id=?", (campaign_id,))
        if not campaign:
            raise KeyError("campaign not found")
        campaign["research_seeds"] = load(campaign.pop("research_seeds_json"), [])
        campaign["target_platforms"] = load(campaign.pop("target_platforms_json"), [])
        campaign["watermark"] = load(campaign.pop("watermark_json"), None)
        campaign["sources"] = self.db.all(
            "SELECT * FROM approved_sources WHERE campaign_id=? ORDER BY created_at", (campaign_id,)
        )
        campaign["successful_examples"] = self.db.all(
            "SELECT * FROM successful_examples WHERE campaign_id=? ORDER BY created_at",
            (campaign_id,),
        )
        requirements = self.db.all(
            "SELECT * FROM campaign_requirements WHERE campaign_id=? ORDER BY created_at",
            (campaign_id,),
        )
        for requirement in requirements:
            requirement["value"] = load(requirement.pop("value_json"))
        campaign["requirements"] = requirements
        campaign["job"] = self.db.one(
            "SELECT * FROM pipeline_jobs WHERE campaign_id=? ORDER BY created_at DESC LIMIT 1",
            (campaign_id,),
        )
        return campaign

    def list_campaigns(self) -> list[dict[str, Any]]:
        return self.db.all(
            "SELECT c.*, (SELECT COUNT(*) FROM approved_sources s WHERE s.campaign_id=c.id) AS source_count, "
            "(SELECT COUNT(*) FROM clip_variants v JOIN candidate_moments m ON m.id=v.candidate_id WHERE m.campaign_id=c.id) AS variant_count "
            ",(SELECT j.current_stage FROM pipeline_jobs j WHERE j.campaign_id=c.id ORDER BY j.created_at DESC LIMIT 1) AS current_stage "
            "FROM campaigns c ORDER BY c.created_at DESC"
        )

    def edit_campaign(self, campaign_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        campaign = self.db.one("SELECT * FROM campaigns WHERE id=?", (campaign_id,))
        if not campaign:
            raise KeyError("campaign not found")
        allowed = {"name", "owner_email", "deadline", "payout_model", "payout_value", "currency"}
        applied = {key: value for key, value in changes.items() if key in allowed}
        if applied:
            assignments = ",".join(f"{key}=?" for key in applied)
            self.db.execute(
                f"UPDATE campaigns SET {assignments},updated_at=? WHERE id=?",
                (*applied.values(), now(), campaign_id),
            )
        if "requirements" in changes:
            for requirement in changes["requirements"]:
                self._insert_requirement(campaign_id, requirement)
            applied["requirements_added"] = len(changes["requirements"])
        self.db.audit("campaign", campaign_id, "edited", {"changes": applied})
        return self.get_campaign(campaign_id)

    def review_bundle(self, campaign_id: str) -> dict[str, Any]:
        campaign = self.get_campaign(campaign_id)
        variants = self.db.all(
            "SELECT v.*,m.source_item_id,m.start_ms,m.end_ms,m.transcript,m.discovery_pass,m.research_match_json,"
            "m.evidence_ids_json,m.scores_json,m.selection_reason,m.saturation_json,m.policy_id,s.title AS source_title,"
            "s.source_url FROM clip_variants v JOIN candidate_moments m ON m.id=v.candidate_id "
            "JOIN source_items s ON s.id=m.source_item_id WHERE m.campaign_id=? ORDER BY v.predicted_score DESC,v.version DESC",
            (campaign_id,),
        )
        for variant in variants:
            for key in (
                "render_spec_json",
                "deterministic_qa_json",
                "ai_qa_json",
                "research_match_json",
                "evidence_ids_json",
                "scores_json",
                "saturation_json",
            ):
                variant[key.removesuffix("_json")] = load(variant.pop(key), {})
            variant["reviews"] = self.db.all(
                "SELECT * FROM reviews WHERE clip_variant_id=? ORDER BY created_at",
                (variant["id"],),
            )
        brief = self.db.one("SELECT * FROM strategy_briefs WHERE campaign_id=?", (campaign_id,))
        if brief:
            brief = {
                "id": brief["id"],
                "brief": load(brief["brief_json"]),
                "evidence_ids": load(brief["evidence_ids_json"]),
            }
        return {"campaign": campaign, "strategy": brief, "variants": variants}

    def review(self, variant_id: str, payload: ReviewInput) -> dict[str, Any]:
        variant = self.db.one("SELECT * FROM clip_variants WHERE id=?", (variant_id,))
        if not variant:
            raise KeyError("clip variant not found")
        if payload.decision == "approve" and variant["qa_status"] != "passed":
            raise PermissionError("deterministic QA must pass before approval")
        review_id = uid()
        self.db.execute(
            "INSERT INTO reviews(id,clip_variant_id,decision,reason_code,feedback_text,created_at) VALUES (?,?,?,?,?,?)",
            (
                review_id,
                variant_id,
                payload.decision,
                payload.reason_code,
                payload.feedback_text,
                now(),
            ),
        )
        result: dict[str, Any] = {"review_id": review_id, "decision": payload.decision}
        if payload.decision == "approve":
            approval = self.db.one("SELECT * FROM approvals WHERE clip_variant_id=?", (variant_id,))
            if not approval:
                approval_id = uid()
                self.db.execute(
                    "INSERT INTO approvals(id,clip_variant_id,review_id,approved_at) VALUES (?,?,?,?)",
                    (approval_id, variant_id, review_id, now()),
                )
            else:
                approval_id = approval["id"]
            result["approval_id"] = approval_id
        elif payload.decision == "change":
            result.update(
                self._create_child_variant(variant, review_id, payload.feedback_text or "")
            )
        self.db.audit(
            "clip_variant",
            variant_id,
            f"review_{payload.decision}",
            {"review_id": review_id, "reason": payload.reason_code},
        )
        return result

    def _create_child_variant(
        self, parent: dict[str, Any], review_id: str, instruction: str
    ) -> dict[str, Any]:
        current = load(parent["render_spec_json"])
        changes = parse_edit_instruction(instruction, current)
        spec = apply_changes(current, changes)
        candidate = self.db.one(
            "SELECT * FROM candidate_moments WHERE id=?", (parent["candidate_id"],)
        )
        max_version = (
            self.db.one(
                "SELECT MAX(version) AS n FROM clip_variants WHERE candidate_id=?",
                (parent["candidate_id"],),
            )["n"]
            or 0
        )
        child_id = uid()
        render = self.pipeline.providers.renderer.render(candidate["campaign_id"], child_id, spec)
        spec["render"] = {"renderer": render.renderer, "sha256": render.sha256}
        requirements = self.pipeline._requirements(candidate["campaign_id"])
        approved_items = {
            row["id"]
            for row in self.db.all(
                "SELECT id FROM source_items WHERE campaign_id=?", (candidate["campaign_id"],)
            )
        }
        report = deterministic_qa(spec, requirements, approved_items)
        self.db.execute(
            "INSERT INTO clip_variants(id,candidate_id,parent_id,style_profile_id,version,render_spec_json,file_uri,qa_status,"
            "deterministic_qa_json,ai_qa_json,predicted_score,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                child_id,
                parent["candidate_id"],
                parent["id"],
                parent["style_profile_id"],
                max_version + 1,
                dump(spec),
                render.file_uri,
                "passed" if report["passed"] else "failed",
                dump(report),
                parent["ai_qa_json"],
                parent["predicted_score"],
                now(),
            ),
        )
        edit_id = uid()
        self.db.execute(
            "INSERT INTO edit_requests(id,clip_variant_id,child_variant_id,instruction,parsed_changes_json,status,created_at) VALUES (?,?,?,?,?,?,?)",
            (edit_id, parent["id"], child_id, instruction, dump(changes), "completed", now()),
        )
        return {
            "edit_request_id": edit_id,
            "child_variant_id": child_id,
            "parsed_changes": changes,
            "qa_status": "passed" if report["passed"] else "failed",
        }

    def publish(self, variant_id: str, payload: PublishInput) -> dict[str, Any]:
        row = self.db.one(
            "SELECT v.*,a.id AS approval_id,m.campaign_id,m.source_item_id,s.approved_source_id,c.name AS campaign_name "
            "FROM clip_variants v JOIN approvals a ON a.clip_variant_id=v.id AND a.revoked_at IS NULL "
            "JOIN candidate_moments m ON m.id=v.candidate_id JOIN source_items s ON s.id=m.source_item_id "
            "JOIN campaigns c ON c.id=m.campaign_id WHERE v.id=?",
            (variant_id,),
        )
        if not row:
            raise PermissionError("explicit approval record required before publication")
        if row["qa_status"] != "passed":
            raise PermissionError("deterministic QA failure blocks publication")
        approved = self.db.one(
            "SELECT id FROM approved_sources WHERE id=? AND campaign_id=?",
            (row["approved_source_id"], row["campaign_id"]),
        )
        if not approved:
            raise PermissionError("publication source is not approved for campaign")
        key = f"publication:{variant_id}:{payload.platform}:{payload.account_id or 'manual'}"
        existing = self.db.one("SELECT * FROM publications WHERE idempotency_key=?", (key,))
        if existing:
            return existing
        publication_id = uid()
        export = self.pipeline.providers.publication.publish_or_export(
            {
                "publication_id": publication_id,
                "campaign": row["campaign_name"],
                "clip_file": row["file_uri"],
                "caption": payload.caption,
                "platform": payload.platform,
                "approval_id": row["approval_id"],
            },
            key,
        )
        self.db.execute(
            "INSERT INTO publications(id,clip_variant_id,platform,account_id,approval_id,status,idempotency_key,external_post_id,url,export_uri,published_at,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                publication_id,
                variant_id,
                payload.platform,
                payload.account_id,
                row["approval_id"],
                export["status"],
                key,
                export.get("external_post_id"),
                export.get("url"),
                export.get("export_uri"),
                export.get("published_at"),
                now(),
            ),
        )
        self.db.audit(
            "publication",
            publication_id,
            "export_prepared",
            {"approval_id": row["approval_id"], "platform": payload.platform},
        )
        return self.db.one("SELECT * FROM publications WHERE id=?", (publication_id,)) or {}

    def record_feedback(self, campaign_id: str, payload: FeedbackInput) -> dict[str, Any]:
        feedback_id = uid()
        self.db.execute(
            "INSERT INTO feedback(id,campaign_id,clip_variant_id,rating,reason_code,feedback_text,human_minutes,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                feedback_id,
                campaign_id,
                payload.clip_variant_id,
                payload.rating,
                payload.reason_code,
                payload.feedback_text,
                payload.human_minutes,
                now(),
            ),
        )
        return self.db.one("SELECT * FROM feedback WHERE id=?", (feedback_id,)) or {}

    def record_performance(self, publication_id: str, payload: PerformanceInput) -> dict[str, Any]:
        if not self.db.one("SELECT id FROM publications WHERE id=?", (publication_id,)):
            raise KeyError("publication not found")
        snapshot_id = uid()
        metrics = payload.model_dump(
            include={"views", "likes", "comments", "shares", "qualified_views", "accepted"}
        )
        revenue = payload.model_dump(include={"revenue", "payout", "currency"})
        baseline = {"views": payload.account_baseline_views}
        self.db.execute(
            "INSERT INTO performance_snapshots(id,publication_id,captured_at,metrics_json,revenue_json,account_baseline_json) VALUES (?,?,?,?,?,?)",
            (snapshot_id, publication_id, now(), dump(metrics), dump(revenue), dump(baseline)),
        )
        return {
            "id": snapshot_id,
            "metrics": metrics,
            "revenue": revenue,
            "account_baseline": baseline,
        }

    def outcomes(self, campaign_id: str) -> dict[str, Any]:
        rows = self.db.all(
            "SELECT v.id AS variant_id,v.predicted_score,r.decision,f.rating,p.id AS publication_id,ps.metrics_json,ps.revenue_json "
            "FROM candidate_moments m JOIN clip_variants v ON v.candidate_id=m.id "
            "LEFT JOIN reviews r ON r.clip_variant_id=v.id LEFT JOIN feedback f ON f.clip_variant_id=v.id "
            "LEFT JOIN publications p ON p.clip_variant_id=v.id LEFT JOIN performance_snapshots ps ON ps.publication_id=p.id "
            "WHERE m.campaign_id=?",
            (campaign_id,),
        )
        disagreements = []
        for row in rows:
            metrics = load(row["metrics_json"], {})
            revenue = load(row["revenue_json"], {})
            market_good = metrics.get("views", 0) > 0 or revenue.get("revenue", 0) > 0
            user_good = row["decision"] == "approve" or (row["rating"] or 0) >= 4
            if row["metrics_json"] and market_good != user_good:
                disagreements.append(
                    {
                        "variant_id": row["variant_id"],
                        "user_positive": user_good,
                        "market_positive": market_good,
                    }
                )
        return {"records": rows, "preference_market_disagreements": disagreements}

    def create_experiment(self, payload: ExperimentInput) -> dict[str, Any]:
        active = self.db.one(
            "SELECT * FROM strategy_policies WHERE active=1 ORDER BY version DESC LIMIT 1"
        )
        max_version = self.db.one("SELECT MAX(version) AS n FROM strategy_policies")["n"] or 0
        treatment_id = uid()
        self.db.execute(
            "INSERT INTO strategy_policies(id,version,weights_json,exploration_pct,active,created_at,supersedes_id) VALUES (?,?,?,?,?,?,?)",
            (
                treatment_id,
                max_version + 1,
                dump(payload.treatment_weights),
                payload.allocation,
                0,
                now(),
                active["id"],
            ),
        )
        experiment_id = uid()
        self.db.execute(
            "INSERT INTO experiments(id,hypothesis,control_policy_id,treatment_policy_id,allocation,status,outcome_json,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                experiment_id,
                payload.hypothesis,
                active["id"],
                treatment_id,
                payload.allocation,
                "planned",
                "{}",
                now(),
            ),
        )
        self.db.execute(
            "INSERT INTO research_ledger(id,entry_type,finding,evidence_json,confidence,decision,applies_to_json,policy_id,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                uid(),
                "hypothesis",
                payload.hypothesis,
                dump({"experiment_id": experiment_id}),
                0.5,
                "planned_experiment",
                dump({"allocation": payload.allocation}),
                treatment_id,
                now(),
            ),
        )
        return self.db.one("SELECT * FROM experiments WHERE id=?", (experiment_id,)) or {}

    def evaluate_experiment(
        self, experiment_id: str, activate_treatment: bool, summary: str
    ) -> dict[str, Any]:
        experiment = self.db.one("SELECT * FROM experiments WHERE id=?", (experiment_id,))
        if not experiment:
            raise KeyError("experiment not found")
        outcome = {"summary": summary, "winner": "treatment" if activate_treatment else "control"}
        self.db.execute(
            "UPDATE experiments SET status='evaluated',outcome_json=? WHERE id=?",
            (dump(outcome), experiment_id),
        )
        if activate_treatment:
            self.db.execute("UPDATE strategy_policies SET active=0 WHERE active=1")
            self.db.execute(
                "UPDATE strategy_policies SET active=1 WHERE id=?",
                (experiment["treatment_policy_id"],),
            )
        self.db.execute(
            "INSERT INTO research_ledger(id,entry_type,finding,evidence_json,confidence,decision,applies_to_json,policy_id,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                uid(),
                "experiment_result",
                summary,
                dump({"experiment_id": experiment_id}),
                0.7,
                outcome["winner"],
                dump({}),
                experiment["treatment_policy_id" if activate_treatment else "control_policy_id"],
                now(),
            ),
        )
        return {**experiment, "status": "evaluated", "outcome": outcome}

    def activate_policy(self, policy_id: str, reason: str) -> dict[str, Any]:
        policy = self.db.one("SELECT * FROM strategy_policies WHERE id=?", (policy_id,))
        if not policy:
            raise KeyError("strategy policy not found")
        self.db.execute("UPDATE strategy_policies SET active=0 WHERE active=1")
        self.db.execute("UPDATE strategy_policies SET active=1 WHERE id=?", (policy_id,))
        self.db.execute(
            "INSERT INTO research_ledger(id,entry_type,finding,evidence_json,confidence,decision,applies_to_json,policy_id,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                uid(),
                "policy_activation",
                reason,
                dump({"policy_version": policy["version"]}),
                1.0,
                "activated_policy",
                dump({}),
                policy_id,
                now(),
            ),
        )
        return {**policy, "active": 1}

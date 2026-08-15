from __future__ import annotations

import binascii
import hashlib
import json
from pathlib import Path
from typing import Any

from .db import Database, dump, load, now, uid
from .domain import apply_changes, cosine, deterministic_qa, embedding
from .pipeline import Pipeline
from .providers import canonical_url, decode_upload, stable_id
from .schemas import (
    CampaignCreate,
    ConnectedAccountCreate,
    ExperimentInput,
    FeedbackInput,
    ImportedTranscriptSegment,
    PerformanceInput,
    PublishInput,
    RequirementUpdate,
    ResearchImportBatch,
    ReviewInput,
)


class AlphaService:
    def __init__(self, db: Database, pipeline: Pipeline):
        self.db = db
        self.pipeline = pipeline

    def create_campaign(self, payload: CampaignCreate) -> dict[str, Any]:
        for account_id in payload.target_account_ids:
            if not self.db.one("SELECT id FROM connected_accounts WHERE id=?", (account_id,)):
                raise ValueError(f"connected account not found: {account_id}")
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
                    {
                        ".png": "image/png",
                        ".jpg": "image/jpeg",
                        ".jpeg": "image/jpeg",
                        ".webp": "image/webp",
                        ".ppm": "image/x-portable-pixmap",
                    }[suffix],
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
                "INSERT INTO research_targets(id,campaign_id,target_type,value) VALUES (?,?,?,?) "
                "ON CONFLICT DO NOTHING",
                (uid(), campaign_id, "keyword", seed),
            )
        for account_id in payload.target_account_ids:
            self.db.execute(
                "INSERT INTO campaign_accounts(campaign_id,account_id,created_at) VALUES (?,?,?) "
                "ON CONFLICT DO NOTHING",
                (campaign_id, account_id, timestamp),
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

    def import_authorised_source(
        self,
        campaign_id: str,
        filename: str,
        content_type: str,
        content: bytes,
        transcript_json: str,
        rights_attestation: str,
        title: str | None = None,
        approved_source_id: str | None = None,
        external_id: str | None = None,
    ) -> dict[str, Any]:
        campaign = self.db.one("SELECT * FROM campaigns WHERE id=?", (campaign_id,))
        if not campaign:
            raise KeyError("campaign not found")
        if campaign["status"] != "draft":
            raise PermissionError("sources can only be imported before campaign submission")
        if len(rights_attestation.strip()) < 12:
            raise ValueError("a clear source-rights attestation is required")
        if not content or len(content) > 500_000_000:
            raise ValueError("source media must be between 1 byte and 500 MB")
        suffix = Path(filename).suffix.lower()
        allowed = {
            ".mp4": "video/mp4",
            ".mov": "video/quicktime",
            ".mkv": "video/x-matroska",
            ".webm": "video/webm",
        }
        if suffix not in allowed:
            raise ValueError("unsupported source media format")
        try:
            raw_segments = json.loads(transcript_json)
            segments = [
                ImportedTranscriptSegment.model_validate(segment).model_dump()
                for segment in raw_segments
            ]
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError(
                "transcript_json must be a valid list of timestamped segments"
            ) from exc
        if not segments:
            raise ValueError("at least one timestamped transcript segment is required")
        segments.sort(key=lambda segment: segment["start_ms"])
        if any(
            current["start_ms"] < previous["end_ms"]
            for previous, current in zip(segments, segments[1:], strict=False)
        ):
            raise ValueError("transcript segments must not overlap")

        media_sha256 = hashlib.sha256(content).hexdigest()
        duplicate = self.db.one(
            "SELECT i.id FROM source_imports i JOIN approved_sources s ON s.id=i.approved_source_id "
            "WHERE s.campaign_id=? AND i.media_sha256=?",
            (campaign_id, media_sha256),
        )
        duplicate = duplicate or self.db.one(
            "SELECT i.id FROM linked_source_media i JOIN approved_sources s ON s.id=i.approved_source_id "
            "WHERE s.campaign_id=? AND i.media_sha256=?",
            (campaign_id, media_sha256),
        )
        if duplicate:
            raise ValueError("this source media has already been imported into the campaign")

        linked_source = None
        if external_id and not approved_source_id:
            for candidate_source in self.db.all(
                "SELECT * FROM approved_sources WHERE campaign_id=? AND source_type!='uploaded'",
                (campaign_id,),
            ):
                try:
                    resolved = self.pipeline.providers.source.resolve(
                        candidate_source["source_type"],
                        candidate_source["url"],
                        candidate_source["title"],
                    )
                except Exception:
                    continue
                if any(item["external_id"] == external_id for item in resolved):
                    approved_source_id = candidate_source["id"]
                    break
            if not approved_source_id:
                raise ValueError(
                    "external_id was not found in the campaign's approved YouTube videos/playlists"
                )
        if approved_source_id:
            linked_source = self.db.one(
                "SELECT * FROM approved_sources WHERE id=? AND campaign_id=?",
                (approved_source_id, campaign_id),
            )
            if not linked_source:
                raise ValueError("approved source link does not belong to this campaign")
            if not external_id:
                raise ValueError("external_id is required when linking media to a YouTube source")
            if self.db.one(
                "SELECT id FROM linked_source_media WHERE approved_source_id=? AND external_id=?",
                (approved_source_id, external_id),
            ):
                raise ValueError("authorised media is already linked to this YouTube video")
        approved_source_id = approved_source_id or uid()
        storage_key = (
            f"sources/{campaign_id}/{approved_source_id}-{stable_id(external_id)}{suffix}"
            if external_id
            else f"sources/{campaign_id}/{approved_source_id}{suffix}"
        )
        media_uri = self.pipeline.providers.storage.put_bytes(
            storage_key, content, content_type or allowed[suffix]
        )
        with self.pipeline.providers.storage.materialize(media_uri) as local_media:
            probe = self.pipeline.providers.renderer.probe_media(local_media)
        if not probe["valid"]:
            self.pipeline.providers.storage.delete(media_uri)
            raise ValueError("uploaded source is not a readable video")
        if segments[-1]["end_ms"] > probe["duration_ms"] + 500:
            self.pipeline.providers.storage.delete(media_uri)
            raise ValueError("transcript timestamps exceed the uploaded media duration")

        timestamp = now()
        source_url = f"alpha://authorised-upload/{approved_source_id}"
        metadata = {
            "provider": "authorised_upload",
            "media_sha256": media_sha256,
            "probe": probe,
            "rights_attested": True,
        }
        with self.db.transaction() as connection:
            if linked_source:
                connection.execute(
                    "INSERT INTO linked_source_media(id,approved_source_id,external_id,media_uri,media_sha256,"
                    "original_filename,content_type,transcript_json,rights_attestation,rights_attested_at,created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        uid(),
                        approved_source_id,
                        external_id,
                        media_uri,
                        media_sha256,
                        Path(filename).name,
                        content_type or allowed[suffix],
                        dump(segments),
                        rights_attestation.strip(),
                        timestamp,
                        timestamp,
                    ),
                )
            else:
                connection.execute(
                    "INSERT INTO approved_sources(id,campaign_id,source_type,url,canonical_url,title,status,metadata_json,created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        approved_source_id,
                        campaign_id,
                        "uploaded",
                        source_url,
                        source_url,
                        title or Path(filename).stem,
                        "pending",
                        dump(metadata),
                        timestamp,
                    ),
                )
                connection.execute(
                    "INSERT INTO source_imports(id,approved_source_id,media_uri,media_sha256,original_filename,"
                    "content_type,transcript_json,rights_attestation,rights_attested_at,created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        uid(),
                        approved_source_id,
                        media_uri,
                        media_sha256,
                        Path(filename).name,
                        content_type or allowed[suffix],
                        dump(segments),
                        rights_attestation.strip(),
                        timestamp,
                        timestamp,
                    ),
                )
        self.db.audit(
            "approved_source",
            approved_source_id,
            "authorised_media_imported",
            {
                "campaign_id": campaign_id,
                "media_sha256": media_sha256,
                "segment_count": len(segments),
                "rights_attested": True,
                "linked_external_id": external_id,
            },
        )
        return self.db.one("SELECT * FROM approved_sources WHERE id=?", (approved_source_id,)) or {}

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
        campaign["target_accounts"] = self.db.all(
            "SELECT a.* FROM connected_accounts a JOIN campaign_accounts ca ON ca.account_id=a.id "
            "WHERE ca.campaign_id=? ORDER BY a.created_at",
            (campaign_id,),
        )
        campaign["job"] = self.db.one(
            "SELECT * FROM pipeline_jobs WHERE campaign_id=? ORDER BY created_at DESC LIMIT 1",
            (campaign_id,),
        )
        return campaign

    def create_connected_account(self, payload: ConnectedAccountCreate) -> dict[str, Any]:
        account_id = uid()
        self.db.execute(
            "INSERT INTO connected_accounts(id,platform,display_name,adapter,created_at) "
            "VALUES (?,?,?,?,?)",
            (
                account_id,
                payload.platform,
                payload.display_name,
                payload.adapter,
                now(),
            ),
        )
        self.db.audit(
            "connected_account",
            account_id,
            "created",
            {"platform": payload.platform, "adapter": payload.adapter},
        )
        return self.db.one("SELECT * FROM connected_accounts WHERE id=?", (account_id,)) or {}

    def attach_connected_account(self, campaign_id: str, account_id: str) -> dict[str, Any]:
        if not self.db.one("SELECT id FROM campaigns WHERE id=?", (campaign_id,)):
            raise KeyError("campaign not found")
        account = self.db.one("SELECT * FROM connected_accounts WHERE id=?", (account_id,))
        if not account:
            raise KeyError("connected account not found")
        self.db.execute(
            "INSERT INTO campaign_accounts(campaign_id,account_id,created_at) VALUES (?,?,?) "
            "ON CONFLICT DO NOTHING",
            (campaign_id, account_id, now()),
        )
        self.db.audit(
            "campaign", campaign_id, "connected_account_attached", {"account_id": account_id}
        )
        return account

    def semantic_search(
        self, campaign_id: str, query: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        if not self.db.one("SELECT id FROM campaigns WHERE id=?", (campaign_id,)):
            raise KeyError("campaign not found")
        query_vector = embedding(query)
        rows = self.db.all(
            "SELECT t.*,s.campaign_id,s.approved_source_id,s.source_url,s.title AS source_title "
            "FROM transcript_segments t JOIN source_items s ON s.id=t.source_item_id "
            "JOIN approved_sources a ON a.id=s.approved_source_id AND a.campaign_id=s.campaign_id "
            "WHERE s.campaign_id=?",
            (campaign_id,),
        )
        results = [
            {
                "source_item_id": row["source_item_id"],
                "approved_source_id": row["approved_source_id"],
                "source_url": row["source_url"],
                "source_title": row["source_title"],
                "start_ms": row["start_ms"],
                "end_ms": row["end_ms"],
                "text": row["text"],
                "similarity": round(cosine(load(row["embedding_json"]), query_vector), 6),
            }
            for row in rows
        ]
        return sorted(results, key=lambda row: row["similarity"], reverse=True)[:limit]

    def import_research(self, campaign_id: str, payload: ResearchImportBatch) -> dict[str, Any]:
        campaign = self.db.one("SELECT * FROM campaigns WHERE id=?", (campaign_id,))
        if not campaign:
            raise KeyError("campaign not found")
        if campaign["status"] != "draft":
            raise PermissionError("research observations must be imported before submission")
        timestamp = now()
        imported_ids = []
        with self.db.transaction() as connection:
            for observation in payload.observations:
                observation_id = uid()
                try:
                    connection.execute(
                        "INSERT INTO research_imports(id,campaign_id,platform,url,creator,published_hours_ago,"
                        "metrics_json,baseline_json,transcript,labels_json,raw_json,provenance,imported_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            observation_id,
                            campaign_id,
                            observation.platform,
                            str(observation.url),
                            observation.creator,
                            observation.published_hours_ago,
                            dump(observation.metrics),
                            dump(observation.creator_baseline),
                            observation.transcript,
                            dump(observation.labels),
                            dump(observation.raw),
                            payload.provenance,
                            timestamp,
                        ),
                    )
                except Exception as exc:
                    if "UNIQUE" in str(exc).upper():
                        raise ValueError("duplicate research observation URL") from exc
                    raise
                imported_ids.append(observation_id)
        self.db.audit(
            "campaign",
            campaign_id,
            "research_imported",
            {
                "observation_ids": imported_ids,
                "count": len(imported_ids),
                "provenance": payload.provenance,
            },
        )
        return {"campaign_id": campaign_id, "imported": len(imported_ids), "ids": imported_ids}

    def revise_requirement(
        self, campaign_id: str, requirement_id: str, payload: RequirementUpdate
    ) -> dict[str, Any]:
        requirement = self.db.one(
            "SELECT * FROM campaign_requirements WHERE id=? AND campaign_id=?",
            (requirement_id, campaign_id),
        )
        if not requirement:
            raise KeyError("campaign requirement not found")
        previous = {
            "key": requirement["key"],
            "type": requirement["requirement_type"],
            "operator": requirement["operator"],
            "value": load(requirement["value_json"]),
            "severity": requirement["severity"],
            "source_text": requirement["source_text"],
        }
        replacement = {
            **previous,
            "operator": payload.operator or previous["operator"],
            "value": payload.value,
            "severity": payload.severity or previous["severity"],
            "source_text": payload.source_text
            if payload.source_text is not None
            else previous["source_text"],
        }
        timestamp = now()
        with self.db.transaction() as connection:
            connection.execute(
                "INSERT INTO requirement_revisions(id,requirement_id,campaign_id,previous_json,replacement_json,reason,created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    uid(),
                    requirement_id,
                    campaign_id,
                    dump(previous),
                    dump(replacement),
                    payload.reason,
                    timestamp,
                ),
            )
            connection.execute(
                "UPDATE campaign_requirements SET operator=?,value_json=?,severity=?,source_text=? WHERE id=?",
                (
                    replacement["operator"],
                    dump(replacement["value"]),
                    replacement["severity"],
                    replacement["source_text"],
                    requirement_id,
                ),
            )
        qa_summary = self._reevaluate_campaign_qa(campaign_id)
        self.db.audit(
            "campaign_requirement",
            requirement_id,
            "revised",
            {
                "campaign_id": campaign_id,
                "previous": previous,
                "replacement": replacement,
                "reason": payload.reason,
                "qa_summary": qa_summary,
            },
        )
        return {
            "requirement_id": requirement_id,
            "previous": previous,
            "replacement": replacement,
            "qa_summary": qa_summary,
        }

    def _reevaluate_campaign_qa(self, campaign_id: str) -> dict[str, int]:
        requirements = self.pipeline._requirements(campaign_id)
        approved_items = {
            row["id"]
            for row in self.db.all(
                "SELECT id FROM source_items WHERE campaign_id=?", (campaign_id,)
            )
        }
        variants = self.db.all(
            "SELECT v.* FROM clip_variants v JOIN candidate_moments c ON c.id=v.candidate_id "
            "WHERE c.campaign_id=?",
            (campaign_id,),
        )
        passed = 0
        revoked = 0
        for variant in variants:
            report = deterministic_qa(
                load(variant["render_spec_json"]), requirements, approved_items
            )
            status = "passed" if report["passed"] else "failed"
            self.db.execute(
                "UPDATE clip_variants SET qa_status=?,deterministic_qa_json=? WHERE id=?",
                (status, dump(report), variant["id"]),
            )
            passed += int(report["passed"])
            if not report["passed"]:
                revoked += self.db.execute(
                    "UPDATE approvals SET revoked_at=? WHERE clip_variant_id=? AND revoked_at IS NULL",
                    (now(), variant["id"]),
                )
        return {"variants": len(variants), "passed": passed, "revoked_approvals": revoked}

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
        changes = self.pipeline.providers.ai.interpret_edit_request(instruction, current)
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
        spec["render"] = {
            "renderer": render.renderer,
            "sha256": render.sha256,
            "probe": render.probe,
        }
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
        if payload.account_id:
            account = self.db.one(
                "SELECT a.* FROM connected_accounts a JOIN campaign_accounts ca ON ca.account_id=a.id "
                "WHERE a.id=? AND ca.campaign_id=?",
                (payload.account_id, row["campaign_id"]),
            )
            if not account:
                raise PermissionError("publication account is not selected for this campaign")
            if account["adapter"] != "manual_export":
                raise PermissionError("the selected account has no enabled publication adapter")
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
        revenue_rows = self.db.all(
            "SELECT ps.revenue_json FROM performance_snapshots ps "
            "JOIN publications p ON p.id=ps.publication_id "
            "JOIN clip_variants v ON v.id=p.clip_variant_id "
            "JOIN candidate_moments m ON m.id=v.candidate_id WHERE m.campaign_id=?",
            (campaign_id,),
        )
        total_revenue = sum(
            float(load(row["revenue_json"], {}).get("revenue", 0) or 0) for row in revenue_rows
        )
        published_clips = self.db.one(
            "SELECT COUNT(DISTINCT p.clip_variant_id) AS n FROM publications p "
            "JOIN clip_variants v ON v.id=p.clip_variant_id "
            "JOIN candidate_moments m ON m.id=v.candidate_id WHERE m.campaign_id=?",
            (campaign_id,),
        )["n"]
        human_minutes = self.db.one(
            "SELECT COALESCE(SUM(human_minutes),0) AS n FROM feedback WHERE campaign_id=?",
            (campaign_id,),
        )["n"]
        summary = {
            "total_revenue": round(total_revenue, 2),
            "published_clips": published_clips,
            "human_minutes": human_minutes,
            "revenue_per_clip": round(total_revenue / published_clips, 2)
            if published_clips
            else None,
            "revenue_per_human_hour": round(total_revenue / (human_minutes / 60), 2)
            if human_minutes
            else None,
        }
        return {
            "records": rows,
            "preference_market_disagreements": disagreements,
            "summary": summary,
        }

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
        arm_rows = self.db.all(
            "SELECT a.arm,c.predicted_score,r.decision,ps.metrics_json,ps.revenue_json "
            "FROM experiment_assignments a JOIN candidate_moments c ON c.id=a.candidate_id "
            "LEFT JOIN clip_variants v ON v.candidate_id=c.id "
            "LEFT JOIN reviews r ON r.clip_variant_id=v.id "
            "LEFT JOIN publications p ON p.clip_variant_id=v.id "
            "LEFT JOIN performance_snapshots ps ON ps.publication_id=p.id "
            "WHERE a.experiment_id=?",
            (experiment_id,),
        )
        metrics: dict[str, dict[str, Any]] = {}
        for arm in ("control", "treatment"):
            members = [row for row in arm_rows if row["arm"] == arm]
            metrics[arm] = {
                "assignments": len(members),
                "average_predicted_score": round(
                    sum(row["predicted_score"] for row in members) / len(members), 5
                )
                if members
                else None,
                "approvals": sum(row["decision"] == "approve" for row in members),
                "views": sum(load(row["metrics_json"], {}).get("views", 0) or 0 for row in members),
                "revenue": round(
                    sum(
                        float(load(row["revenue_json"], {}).get("revenue", 0) or 0)
                        for row in members
                    ),
                    2,
                ),
            }
        outcome = {
            "summary": summary,
            "winner": "treatment" if activate_treatment else "control",
            "metrics": metrics,
        }
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

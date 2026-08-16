from __future__ import annotations

import json
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .conftest import campaign_payload


def test_worker_recovers_expired_lease_and_resumes_completed_stages(client, app):
    campaign_id = client.post("/api/campaigns", json=campaign_payload()).json()["id"]
    job = client.post(f"/api/campaigns/{campaign_id}/submit").json()
    pipeline = app.state.pipeline

    for index in range(4):
        result = pipeline.run_once(f"short-worker-{index}")
        assert result["status"] == "queued"
    completed_before = app.state.db.all(
        "SELECT stage FROM pipeline_stage_attempts WHERE job_id=? AND status='completed'",
        (job["id"],),
    )
    assert len(completed_before) == 4

    abandoned = pipeline.acquire("killed-worker")
    assert abandoned["current_stage"] == "social_research"
    expired = (datetime.now(UTC) - timedelta(hours=73)).isoformat()
    app.state.db.execute(
        "UPDATE pipeline_jobs SET lease_expires_at=? WHERE id=?", (expired, job["id"])
    )

    original = pipeline.stage_handlers["social_research"]
    calls = {"count": 0}

    def transient(campaign: str, job_id: str):
        calls["count"] += 1
        if calls["count"] == 1:
            raise ConnectionError("fixture transient provider failure")
        return original(campaign, job_id)

    pipeline.stage_handlers["social_research"] = transient
    failed_attempt = pipeline.run_once("replacement-worker")
    assert failed_attempt["status"] == "retry"
    results = pipeline.run_until_idle("replacement-worker")
    assert results[-1]["status"] == "awaiting_review"

    job_after = app.state.db.one("SELECT * FROM pipeline_jobs WHERE id=?", (job["id"],))
    assert job_after["status"] == "awaiting_review"
    completed_after = app.state.db.all(
        "SELECT stage,COUNT(*) AS n FROM pipeline_stage_attempts "
        "WHERE job_id=? AND status='completed' GROUP BY stage",
        (job["id"],),
    )
    assert len(completed_after) == len(pipeline.stage_handlers)
    assert all(row["n"] == 1 for row in completed_after)
    assert (
        app.state.db.one(
            "SELECT COUNT(*) AS n FROM notifications WHERE campaign_id=?", (campaign_id,)
        )["n"]
        == 1
    )


def test_long_stage_renews_lease_and_blocks_duplicate_worker(client, app):
    campaign_id = client.post("/api/campaigns", json=campaign_payload()).json()["id"]
    job = client.post(f"/api/campaigns/{campaign_id}/submit").json()
    pipeline = app.state.pipeline
    original = pipeline.stage_handlers["validate_campaign"]

    def slow_stage(campaign: str, job_id: str):
        time.sleep(pipeline.settings.lease_seconds * 1.4)
        return original(campaign, job_id)

    pipeline.stage_handlers["validate_campaign"] = slow_stage
    result: dict = {}

    def run_stage():
        result.update(pipeline.run_once("long-stage-worker") or {})

    thread = threading.Thread(target=run_stage)
    thread.start()
    time.sleep(pipeline.settings.lease_seconds * 1.1)
    assert pipeline.acquire("duplicate-worker") is None
    thread.join(timeout=10)
    assert result["status"] == "queued"
    attempt = app.state.db.one(
        "SELECT * FROM pipeline_stage_attempts WHERE job_id=? AND stage='validate_campaign'",
        (job["id"],),
    )
    assert attempt["heartbeat_count"] >= 1


def test_bounded_backoff_and_terminal_failure_email_are_real(client, app):
    campaign_id = client.post("/api/campaigns", json=campaign_payload()).json()["id"]
    job = client.post(f"/api/campaigns/{campaign_id}/submit").json()
    pipeline = app.state.pipeline
    pipeline.settings = replace(pipeline.settings, retry_base_seconds=30, max_job_attempts=5)

    def permanent_failure(_campaign: str, _job_id: str):
        raise ConnectionError("secret-token=must-not-appear-in-email")

    pipeline.stage_handlers["validate_campaign"] = permanent_failure
    first = pipeline.run_once("failure-worker")
    assert first["status"] == "retry"
    queued = app.state.db.one("SELECT * FROM pipeline_jobs WHERE id=?", (job["id"],))
    assert queued["available_at"] > datetime.now(UTC).isoformat()
    assert pipeline.acquire("too-early-worker") is None

    for attempt in range(1, 5):
        app.state.db.execute(
            "UPDATE pipeline_jobs SET available_at=? WHERE id=?",
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), job["id"]),
        )
        result = pipeline.run_once(f"failure-worker-{attempt}")
    assert result["status"] == "failed"
    assert (
        app.state.db.one("SELECT status FROM campaigns WHERE id=?", (campaign_id,))["status"]
        == "failed_needs_attention"
    )
    notifications = app.state.db.all(
        "SELECT * FROM notifications WHERE campaign_id=? AND notification_type='failed_needs_attention'",
        (campaign_id,),
    )
    assert len(notifications) == 1
    message = json.loads(Path(notifications[0]["file_uri"]).read_text(encoding="utf-8"))
    assert "secret-token" not in message["body"]
    assert "ConnectionError" in message["body"]
    assert campaign_id in message["body"]
    failed_job = app.state.db.one("SELECT error_json FROM pipeline_jobs WHERE id=?", (job["id"],))
    assert "must-not-appear" not in failed_job["error_json"]
    assert "[REDACTED]" in failed_job["error_json"]


def test_missing_watermark_blocks_until_audited_rule_revision(client, app):
    payload = campaign_payload(watermark=False)
    campaign_id = client.post("/api/campaigns", json=payload).json()["id"]
    client.post(f"/api/campaigns/{campaign_id}/submit")
    client.post("/api/dev/worker/run-until-idle")
    variant = client.get(f"/api/campaigns/{campaign_id}/review").json()["variants"][0]
    assert variant["qa_status"] == "failed"
    assert any(
        failure["key"] == "watermark_present"
        for failure in variant["deterministic_qa"]["blocking_failures"]
    )
    approval = client.post(f"/api/variants/{variant['id']}/review", json={"decision": "approve"})
    assert approval.status_code == 409
    publish = client.post(
        f"/api/variants/{variant['id']}/publish", json={"platform": "manual_export"}
    )
    assert publish.status_code == 409
    campaign = client.get(f"/api/campaigns/{campaign_id}").json()
    requirement = next(row for row in campaign["requirements"] if row["key"] == "watermark_present")
    revised = client.patch(
        f"/api/campaigns/{campaign_id}/requirements/{requirement['id']}",
        json={
            "value": False,
            "reason": "Campaign owner confirmed that this delivery does not require a watermark.",
        },
    )
    assert revised.status_code == 200, revised.text
    assert revised.json()["previous"]["value"] is True
    assert revised.json()["replacement"]["value"] is False
    updated = client.get(f"/api/campaigns/{campaign_id}/review").json()["variants"][0]
    assert updated["qa_status"] == "passed"
    assert (
        client.post(
            f"/api/variants/{variant['id']}/review", json={"decision": "approve"}
        ).status_code
        == 200
    )
    revision = app.state.db.one(
        "SELECT * FROM requirement_revisions WHERE requirement_id=?", (requirement["id"],)
    )
    assert revision
    audit = app.state.db.one(
        "SELECT * FROM audit_log WHERE entity_type='campaign_requirement' AND entity_id=?",
        (requirement["id"],),
    )
    assert audit


def test_policy_experiment_is_auditable_and_rollback_remains_possible(client, app):
    active = app.state.db.one("SELECT * FROM strategy_policies WHERE active=1")
    weights = {"research_alignment": 2.0, "hook_quality": 1.0}
    experiment = client.post(
        "/api/experiments",
        json={
            "hypothesis": "More research alignment improves return",
            "treatment_weights": weights,
            "allocation": 0.15,
        },
    )
    assert experiment.status_code == 201
    experiment_id = experiment.json()["id"]
    evaluated = client.post(
        f"/api/experiments/{experiment_id}/evaluate",
        json={"activate_treatment": True, "summary": "Treatment won fixture evaluation."},
    )
    assert evaluated.status_code == 200
    new_active = app.state.db.one("SELECT * FROM strategy_policies WHERE active=1")
    assert new_active["id"] != active["id"]
    assert new_active["supersedes_id"] == active["id"]
    assert app.state.db.one("SELECT * FROM strategy_policies WHERE id=?", (active["id"],))
    rollback = client.post(
        f"/api/policies/{active['id']}/activate",
        json={"reason": "Rollback after observed regression"},
    )
    assert rollback.status_code == 200
    assert app.state.db.one("SELECT id FROM strategy_policies WHERE active=1")["id"] == active["id"]


def test_experiment_assigns_control_and_treatment_before_prediction(client, app):
    experiment = client.post(
        "/api/experiments",
        json={
            "hypothesis": "Research-heavy weights improve candidate quality",
            "treatment_weights": {
                "research_alignment": 2.5,
                "hook_quality": 0.8,
                "campaign_relevance": 1.5,
            },
            "allocation": 0.4,
        },
    ).json()
    campaign_id = client.post(
        "/api/campaigns", json=campaign_payload(source_count=8, example_count=3)
    ).json()["id"]
    client.post(f"/api/campaigns/{campaign_id}/submit")
    for index in range(7):
        result = app.state.pipeline.run_once(f"assignment-worker-{index}")
        assert result["status"] == "queued"
    assignments = app.state.db.all(
        "SELECT a.*,c.policy_id AS candidate_policy_id FROM experiment_assignments a "
        "JOIN candidate_moments c ON c.id=a.candidate_id WHERE a.experiment_id=?",
        (experiment["id"],),
    )
    candidates = app.state.db.one(
        "SELECT COUNT(*) AS n FROM candidate_moments WHERE campaign_id=?", (campaign_id,)
    )["n"]
    assert len(assignments) == candidates
    assert {row["arm"] for row in assignments} == {"control", "treatment"}
    assert all(row["policy_id"] == row["candidate_policy_id"] for row in assignments)
    evaluated = client.post(
        f"/api/experiments/{experiment['id']}/evaluate",
        json={"activate_treatment": False, "summary": "Control retained after fixture run."},
    )
    assert evaluated.status_code == 200
    metrics = evaluated.json()["outcome"]["metrics"]
    assert metrics["control"]["assignments"] > 0
    assert metrics["treatment"]["assignments"] > 0

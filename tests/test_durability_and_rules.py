from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .conftest import campaign_payload


def test_worker_recovers_expired_lease_and_resumes_completed_stages(client, app):
    campaign_id = client.post("/api/campaigns", json=campaign_payload()).json()["id"]
    job = client.post(f"/api/campaigns/{campaign_id}/submit").json()
    pipeline = app.state.pipeline

    for index in range(4):
        result = pipeline.run_once(f"short-worker-{index}")
        assert result["status"] == "queued"
    completed_before = app.state.db.all(
        "SELECT stage FROM stage_runs WHERE job_id=? AND status='completed'", (job["id"],)
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
        "SELECT stage,COUNT(*) AS n FROM stage_runs WHERE job_id=? AND status='completed' GROUP BY stage",
        (job["id"],),
    )
    assert len(completed_after) == 11
    assert all(row["n"] == 1 for row in completed_after)
    assert (
        app.state.db.one(
            "SELECT COUNT(*) AS n FROM notifications WHERE campaign_id=?", (campaign_id,)
        )["n"]
        == 1
    )


def test_missing_mandatory_watermark_blocks_approval_and_publish(client):
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

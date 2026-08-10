# ALPHA — Architecture Decision Log

Use this format for meaningful decisions.

## ADR-000 — Baseline principles

Status: Accepted

Decision:
- Alpha uses durable checkpointed jobs rather than assuming one worker process survives for the whole campaign.
- Deterministic campaign compliance and AI judgement are separate systems.
- External AI/research/storage/email/publishing services are accessed through provider interfaces.
- Human approval is mandatory before publication in V0.
- Research evidence is preserved separately from derived recommendations.

Reason:
These decisions support unattended processing, auditability, provider flexibility, and safe iteration.

---

## ADR template

### ADR-XXX — Title
Status: Proposed / Accepted / Superseded

Context:

Decision:

Consequences:

Alternatives considered:

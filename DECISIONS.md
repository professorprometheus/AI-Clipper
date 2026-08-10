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

---

### ADR-001 — SQLite queue and short leased stage executions
Status: Accepted

Context:
The free local path needs durable work without Redis or a continuously connected browser, and a logical campaign can span 72+ hours.

Decision:
Use the application database as the queue. A worker atomically leases one stage, persists its side effects/checkpoint, then releases the job for the next short execution. Expired leases are recoverable; side effects have uniqueness/idempotency keys.

Consequences:
Local development needs only SQLite. PostgreSQL can later implement the same queue contract with row locking. SQLite write throughput is deliberately accepted as a V0 limit.

Alternatives considered:
Redis/Celery and a single long-lived background task were rejected as either adding infrastructure or violating resumability.

---

### ADR-002 — Compliant fixture/manual provider path
Status: Accepted

Context:
No platform credentials or content-access grants exist in the repository, but the full vertical pipeline must be demonstrable.

Decision:
Implement real provider contracts with deterministic authorised fixtures and a manual/import fallback. Fixture records are explicitly labelled and never presented as live observations. Direct third-party downloading or access-control circumvention is absent.

Consequences:
CI and local demos are deterministic and free. Production decisions require permitted platform adapters or user-authorised imports before being described as live.

Alternatives considered:
Scraping public pages was rejected because it is brittle and may violate platform controls or terms.

---

### ADR-003 — Real FFmpeg render over generated authorised media
Status: Accepted

Context:
Rendering and deterministic QA require actual video output, while third-party source footage cannot be safely bundled or fetched without rights.

Decision:
Use the system FFmpeg or the free `imageio-ffmpeg` binary to generate H.264/AAC 9:16 fixture video, burn captions and overlay the campaign watermark. The RenderSpec/provider boundary is the same one a future authorised-media renderer consumes.

Consequences:
Tests exercise a real encoder and video files without copyrighted fixtures. Fixture renders do not claim to be clips of the remote source.

Alternatives considered:
Fake `.mp4` placeholders were rejected; repository-bundled third-party media was rejected on rights/provenance grounds.

---

### ADR-004 — Explicit approval produces an export by default
Status: Accepted

Context:
Platform posting APIs require approval and credentials, and some desired platforms may not expose a suitable direct V0 posting route.

Decision:
Persist approval first, re-check QA and source provenance, then create an idempotent manual export package. Live platform adapters may replace the final delivery action without weakening the gate.

Consequences:
V0 has a functional publication path without bypassing controls or requiring paid infrastructure.

Alternatives considered:
Browser automation for posting was rejected as unsafe and non-compliant.

---

### ADR-005 — Immutable review/edit and policy lineage
Status: Accepted

Context:
Alpha must learn from feedback without losing rejected renders, original evidence, or the prediction that existed before outcomes.

Decision:
Every change request creates a child ClipVariant. Reviews are append-only. Every candidate records its StrategyPolicy; experiments create inactive policy versions that can be activated or rolled back only through an audited action.

Consequences:
Human and market disagreement can be inspected historically, and learning changes configuration rather than source code.

Alternatives considered:
Mutating a single render/policy row was rejected because it destroys evaluation provenance.

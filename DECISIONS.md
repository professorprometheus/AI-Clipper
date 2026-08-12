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

---

### ADR-006 — Lease renewal, persisted backoff, and attempt history
Status: Accepted

Context:
FFmpeg work can outlast the original short lease. A second worker must not acquire the same stage, while transient failures still need durable retry timing and useful history.

Decision:
Renew the stage lease from a bounded heartbeat thread while work is active. Guard completion/failure updates with the lease token, store every attempt separately, and persist exponential retry availability. A terminal failure sends one secret-redacted attention notification and moves the campaign to an explicit attention state.

Consequences:
Long stages remain mutually exclusive without requiring a long static lease. Operators can inspect retries without losing prior attempts, and a stale worker cannot commit after losing ownership.

Alternatives considered:
A lease longer than every possible render and overwriting one attempt row were rejected because they weaken recovery and erase operational evidence.

---

### ADR-007 — Rights-attested local imports are the real-media fallback
Status: Accepted

Context:
ALPHA needs to process real source media and research evidence, but the repository has no permission to fetch third-party content or platform data.

Decision:
Accept local video only with an explicit rights attestation and validated timestamped transcript. Store file hashes, provenance and import audit records before pipeline use. Accept research observations through an audited manual batch and preserve the raw import separately from derived clusters and creator profiles.

Consequences:
The V0 can render genuine authorised footage and analyse non-fixture evidence without bypassing platform controls. Users remain responsible for supplying permitted material.

Alternatives considered:
Implicit URL downloading and treating copied metrics as live provider observations were rejected for compliance and provenance reasons.

---

### ADR-008 — Single-admin database sessions for protected V0 deployments
Status: Accepted

Context:
The dashboard and unsafe API operations need authentication and CSRF protection, while the free single-user path should not require an external identity service.

Decision:
Provide optional local single-admin login backed by hashed, expiring, revocable database sessions. Use HttpOnly SameSite cookies plus a separate CSRF token for unsafe browser requests. Fail startup when authentication is required but credentials are absent, and retain the constant-time API-token option for non-browser clients.

Consequences:
Local development remains simple and deployments can be protected without storing plaintext session tokens. Multi-user roles, OAuth and external identity lifecycle are explicitly future production work.

Alternatives considered:
Browser-only API keys and unauthenticated production defaults were rejected because they do not provide safe session or CSRF semantics.

---

### ADR-009 — Experiment assignment precedes candidate scoring
Status: Accepted

Context:
An experiment is not auditable if the treatment arm is selected after observing model scores or outcomes.

Decision:
Assign each candidate deterministically to control or treatment from stable identifiers and the configured allocation before scoring. Persist both the assignment and applied policy, then summarise predicted and observed metrics by arm.

Consequences:
Retries preserve assignments and comparisons are reproducible. Exploration remains configurable without automatic source-code changes.

Alternatives considered:
Random assignment on every run and post-score bucketing were rejected because they are unstable or biased.

---

### ADR-010 — Resend for production notification delivery
Status: Accepted

Context:
The file email sink is suitable for local development but cannot notify a user after remote background processing. The production path needs retry-safe delivery without replacing the free local workflow.

Decision:
Implement Resend's HTTPS email API behind the existing EmailAdapter. Send the durable ALPHA notification key as Resend's idempotency key, use plain-text bodies, retain only the returned email ID, and automatically select Resend when an API key is present. Require a configured sender at a verified domain and expose only boolean readiness in deployment diagnostics.

Consequences:
Supplying `RESEND_API_KEY` and `RESEND_FROM_EMAIL` enables production delivery without changing pipeline code. Local/CI environments remain credential-free through the file adapter. Live delivery remains unverified until real credentials and DNS are supplied.

Alternatives considered:
An SDK dependency was unnecessary for one stable HTTPS endpoint. SMTP was not selected because Resend's API exposes a direct idempotency header and structured delivery ID.

---

### ADR-011 — Official live providers with explicit access degradation
Status: Accepted

Context:
Build #2 must use real approved YouTube sources and current external evidence without scraping private endpoints or disguising manual/fixture data as live research. Platform APIs expose materially different access levels.

Decision:
Use YouTube Data API v3 for source resolution, playlist pagination, metadata and research. Use captions.list/download only through renewable OAuth credentials for tracks the user may edit. Use official TikTok oEmbed for supplied examples, the approved TikTok Research API with automatically renewed client credentials when authorized, Instagram Graph hashtag research for authorized professional accounts, and public news indexes as wider-web mention evidence. Persist provider events and raw provenance, isolate failures per source/query, and keep metrics with different semantics explicitly labelled.

Consequences:
YouTube metadata/research is automatic with an API key, while inaccessible captions truthfully require rights-attested media/transcript. TikTok/Instagram depth improves when their approvals are supplied without blocking the base YouTube/public-web workflow. No fixture provider participates in live mode.

Alternatives considered:
Unofficial YouTube transcript endpoints, platform scraping and anti-bot workarounds were rejected. Treating news mentions as views or silently falling back to fixture observations was also rejected.

---

### ADR-012 — Single Render service for the SQLite deployment boundary
Status: Accepted

Context:
The current durable queue and media store are local to SQLite/filesystem. Separate cloud API and worker services cannot safely share a Render persistent disk, and a free ephemeral instance cannot preserve jobs or clips.

Decision:
Deploy one Docker web service that runs the API and one background worker thread against a single encrypted persistent disk. Use Render's starter tier because disks require a paid service. Keep database leases/checkpoints so process restarts remain recoverable, but prevent multi-instance scaling until PostgreSQL/object storage replace the local state boundary.

Consequences:
Closing the user's browser/laptop does not stop processing after deployment. The configuration has a small unavoidable hosting cost and brief deployment downtime, and actual deployment still requires the user's Render account and billing approval.

Alternatives considered:
Render's free ephemeral filesystem fails durability. Separate services with SQLite cannot share state. A PostgreSQL/object-storage migration is the correct later multi-host design but is larger than the one-campaign Build #2 objective.

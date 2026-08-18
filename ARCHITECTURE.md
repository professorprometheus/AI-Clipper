# ALPHA — V0 Technical Architecture

## Architectural goals

- Asynchronous by default.
- Durable jobs.
- Idempotent/retryable stages.
- Provider-agnostic interfaces.
- £0-friendly development path.
- Deterministic compliance.
- Human-in-the-loop publishing.
- Full provenance: every recommendation should link back to evidence.

## Recommended V0 stack

### Front end
- Next.js + TypeScript
- Simple responsive dashboard
- Server-side authenticated application

### API / application backend
- FastAPI (Python)
- Pydantic schemas
- explicit SQLite/Psycopg database gateway
- REST initially; events/webhooks internally where appropriate

### Database
- PostgreSQL in deployed environments
- SQLite permitted for local development/tests
- pgvector optional once semantic scale justifies it

The implemented gateway selects external PostgreSQL from `DATABASE_URL` in deployed environments and retains SQLite for local development/tests. PostgreSQL acquisitions use transactional `FOR UPDATE SKIP LOCKED`; SQLite retains its immediate-write transaction.

### Durable jobs
Implement a queue abstraction, not provider-specific business logic.

Interfaces:
- enqueue(job_type, payload)
- acquire()
- heartbeat()
- retry()
- complete()
- fail()
- resume_from_checkpoint()

For V0:
- database-backed queue is acceptable;
- worker polls pending tasks;
- every pipeline stage stores a checkpoint;
- an active heartbeat renews the lease while a stage is running;
- lease-token guards prevent a stale worker committing after ownership changes;
- retry availability, bounded exponential backoff and each attempt are persisted;
- expired leases are recoverable.

Do not require the browser to remain connected.

### Object storage
Provider abstraction:
- local filesystem adapter for development;
- S3-compatible object-store adapter for deployment.

Store:
- source artefacts if permitted;
- audio extracts;
- transcripts;
- rendered clips;
- thumbnails;
- watermark assets;
- publication exports.

Transcripts are currently database-backed. FFmpeg intermediates are reproducible and invocation-scoped, so they are deleted with the temporary working directory rather than treated as durable artefacts.

### Video/audio
- FFmpeg/ffprobe
- local/open-source transcription adapter (Whisper-compatible)
- optional remote transcription adapter behind interface

Uploaded authorised video/audio is probed and passed to a configured command adapter using
`{input}` and `{output_dir}` placeholders. The command must emit JSON timestamp segments. The
media object, transcript, exact approved-source link and rights attestation are persisted before
pipeline execution; no worker-local path is durable state.

### Rights-safe asset discovery
- reusable Asset cache is searched before any network provider;
- Openverse provides filtered commercial/modification-compatible image results;
- Pexels optionally provides licensed photo/video results when its API key is configured;
- provider interfaces keep additional authorised catalogues replaceable;
- semantic ranking uses the moment, purpose, topic, emotion and punchline signals;
- provider/source/licence/attribution metadata and object URI are persisted together;
- an unavailable or unsuitable asset produces an explicit omission decision, not a job failure.

### AI layer
Provider abstraction:
- classify_content()
- analyse_examples()
- infer_style_profile()
- rank_candidates()
- generate_research_queries()
- evaluate_soft_requirement()
- interpret_edit_request()
- generate_caption_metadata()

V0 must run with at least one local/free-capable adapter.
Never bake one commercial model provider into domain logic.

The current local adapter provides deterministic heuristic example analysis, research-query generation, advisory soft-requirement evaluation and edit interpretation. These outputs remain explicitly AI/advisory and never override deterministic compliance.

### Semantic retrieval
V0:
- embeddings adapter;
- store chunk embeddings with timestamp/source IDs;
- cosine similarity;
- allow local embedding model.

### Live provider boundary
- YouTube Data API v3 handles approved video/playlist resolution, metadata and current video research.
- YouTube caption content is retrieved only with renewable OAuth authorization for tracks the user may edit.
- Missing caption/media access is a recorded per-source limitation, never an unofficial download.
- Rights-attested media/transcript can be linked to the exact YouTube video ID, including playlist items.
- TikTok Research and Instagram Graph enrich research only when their platform approvals exist; official TikTok oEmbed and public news feeds provide narrower automatic evidence.
- `provider_events` preserves successes, partial results and access failures without storing credentials.

### Email
Provider abstraction:
- development console/file email adapter;
- production Resend HTTPS API adapter.
Email only after review-ready or meaningful failure requiring human intervention.

The Resend adapter sends plain-text messages with a provider idempotency key and stores the returned email ID as the delivery URI. The API key stays in environment/secret management and is never persisted or included in delivery errors.

### Publishing
One adapter per platform.

V0 rule:
- prepare publication;
- require explicit approval token;
- post only after approval.
If direct posting API is unavailable/not permitted, provide an export/manual-post flow rather than bypassing platform controls.

Campaigns select one or more enabled ConnectedAccount records. Publication must re-check that the chosen account belongs to the campaign before invoking its adapter.

## Domain model

Campaign
- id
- name
- platform/program
- campaign_url
- payout_model
- payout_amount
- views_per_payout_unit
- payout_rules_json
- currency
- deadline
- status
- created_at

CampaignRequirement
- id
- campaign_id
- key
- type: deterministic | ai_evaluated | informational
- operator
- value
- severity
- source_text

ApprovedSource
- id
- campaign_id
- type: youtube_video | youtube_playlist | uploaded | other
- url
- canonical_source_id
- title
- duration
- status
- metadata_json
- pasted_transcript_json
- transcript_timestamped

SourceItem
Represents a resolved concrete item. A playlist may resolve to many SourceItems.
- id
- approved_source_id
- campaign_id
- source_url
- title
- duration
- channel
- published_at

TranscriptSegment
- id
- source_item_id
- start_ms
- end_ms
- text
- embedding

SuccessfulExample
- id
- campaign_id
- url
- platform
- creator
- metrics_snapshot_json
- transcript
- analysis_json

ResearchTarget
- id
- campaign_id
- type: account | topic | keyword | example | general
- value

ResearchObservation
- id
- campaign_id
- platform
- url
- creator
- observed_at
- published_at
- metrics_json
- creator_baseline_json
- derived_signals_json
- transcript
- qualitative_labels_json

StyleProfile
- id
- campaign_id nullable
- name
- evidence_count
- features_json
- confidence
- provenance_json

TrendCluster
- id
- campaign_id
- label
- embedding
- metrics_json
- lifecycle_state
- evidence_ids

CandidateMoment
- id
- campaign_id
- source_item_id
- start_ms
- end_ms
- transcript
- research_match_json
- scores_json
- selection_reason
- saturation_json
- status

ClipVariant
- id
- candidate_moment_id
- style_profile_id
- render_spec_json
- file_uri
- qa_status
- qa_report_json
- predicted_score

Review
- id
- clip_variant_id
- decision: approve | change | reject
- reason_code
- feedback_text
- created_at

EditRequest
- id
- clip_variant_id
- instruction
- parsed_changes_json
- status

Publication
- id
- clip_variant_id
- platform
- account_id
- approval_id
- status
- external_post_id
- url
- published_at

PerformanceSnapshot
- id
- publication_id
- captured_at
- metrics_json
- revenue_json

Experiment
- id
- hypothesis
- control_policy
- treatment_policy
- allocation
- status
- outcome_json

ResearchLedgerEntry
- id
- hypothesis_or_finding
- evidence_json
- confidence
- decision
- applies_to_json
- created_at

PipelineJob
- id
- campaign_id
- job_type
- status
- current_stage
- attempts
- lease_expires_at
- heartbeat_at
- checkpoint_json
- error_json
- created_at
- updated_at

## Campaign pipeline

STAGE 0 validate_campaign
- validate required inputs;
- normalise campaign requirements;
- validate source URLs;
- ensure at least one approved source.

STAGE 1 resolve_sources
- expand playlists into concrete source items;
- deduplicate;
- fetch permitted metadata;
- resolve rights-attested local SourceImport records without remote fetching;
- checkpoint resolved items.

STAGE 2 ingest_sources
- obtain/access source artefact where permitted;
- extract audio if needed;
- transcribe;
- chunk with timestamps;
- embed/index.

STAGE 3 preflight_sources
- compute metadata/transcript/media/research/render readiness for every approved source;
- require at least one transcript-bearing, renderable approved source before long research;
- stop as `ACTION REQUIRED` with exact missing source IDs and remediation when impossible.

STAGE 4 analyse_successful_examples
- ingest example metadata/transcript where permitted;
- derive hook/topic/structure/style labels;
- infer provisional style profile.

STAGE 5 social_research
- generate research plan from campaign/examples;
- collect available/permitted observations;
- consume audited manual ResearchImport records when a live provider is unavailable;
- identify creator-relative outliers;
- identify velocity and topic clusters;
- analyse successful clipping channels where available;
- store raw evidence and derived signals.

STAGE 6 synthesize_strategy
- infer style profiles;
- rank trend/angle opportunities;
- produce strategy brief;
- explicitly state uncertainty/data gaps.

STAGE 7 discover_candidates
- semantic search over every approved SourceItem;
- independent pass for funny/surprising/emotional/insightful moments;
- detect likely duplicate/overused moments;
- create candidate windows.

STAGE 8 rank_candidates
- score candidate quality;
- research alignment;
- source saturation;
- campaign relevance;
- standalone clarity;
- hook;
- predicted return proxy;
- diversification.
- if ordinary discovery is empty, broaden across funny, surprising, controversial, emotional,
  story, useful and quotable moments; otherwise stop as `ACTION REQUIRED`.

STAGE 9 plan_enrichment
- record evidence-based decisions for every permitted enrichment type;
- choose cache-first, rights-safe external assets only when the clip benefits;
- persist provider/licence/reason lineage before rendering.

STAGE 10 render
- render selected candidates using chosen style profiles;
- enforce deterministic requirements.

STAGE 11 qa
- ffprobe checks;
- duration/aspect/resolution;
- required watermark/branding;
- caption presence where required;
- permitted source provenance;
- AI-evaluated checks separated and labelled;
- fail closed for deterministic mandatory requirements.
- zero passing clips becomes `ACTION REQUIRED` with the blocking mandatory rules.

STAGE 12 review_ready
- persist clip bundle;
- generate evidence-backed review explanations;
- email user;
- job status = awaiting_review.

POST-PIPELINE user_review
External to worker:
- approve/change/reject.
Changes create child render jobs rather than mutating history.

POST-PIPELINE publish
- only approved variants;
- platform adapter;
- retain receipt/external ID.
Fallback to export/manual post if API unsupported.

POST-PIPELINE measure
- capture metrics when available;
- allow manual metric entry;
- compute outcome metrics;
- associate Content Rewards acceptance/revenue.

POST-PIPELINE learn
- add research ledger entries;
- update configurable strategy weights;
- create candidate hypotheses;
- never autonomously deploy source-code changes.

## Durability rules

Every stage MUST:
1. be idempotent or detect existing completed output;
2. persist a checkpoint before moving on;
3. support retry with bounded backoff;
4. emit structured logs;
5. never require browser presence;
6. make partial progress visible;
7. avoid duplicate publishing by using idempotency keys;
8. recover abandoned jobs after lease expiry.

A 72-hour campaign processing job is acceptable. The architecture must not assume a single process remains alive for 72 hours. It must allow many short/medium worker executions to collectively complete one durable job.

## Security / privacy basics

- OAuth/social tokens encrypted at rest where deployment supports it.
- Never print access tokens in logs.
- Secrets only via environment/secret manager.
- Minimal permissions for social posting connectors.
- Signed/unguessable review actions.
- Explicit approval record before publication.
- Audit log for campaign changes, approvals and publications.
- Single-user V0 deployments may use hashed, expiring, revocable database sessions with HttpOnly SameSite cookies and CSRF protection.
- Authentication-required startup fails closed when administrator credentials are missing.
- API-token comparisons are constant-time; exception text is redacted before durable storage or notification.
- OAuth client secrets, refresh tokens and platform API tokens remain environment-only; diagnostics expose booleans, never values.

## Stateless free-tier deployment

The Render Blueprint is a diskless free web service. Application/queue/history state is in external Postgres and durable artefacts use private S3-compatible storage. FFmpeg downloads authorised inputs to an invocation-scoped temporary directory, renders sequentially, uploads the final object, and then commits its `ClipVariant`; no temporary path is durable state.

The web instance has no embedded production worker and may sleep or be destroyed safely. A
scheduled GitHub Actions job starts a fresh worker hourly and may process all 13 checkpointed stages
inside a bounded 120-minute invocation. Each invocation can resume a campaign from Postgres,
including expired leases and persisted retries. The same worker command can move later to
continuous compute without changing queue semantics.

Recommended initial providers are Neon Free Postgres, Cloudflare R2 Standard storage and a Render Free web service. Compute-heavy FFmpeg work runs on a standard GitHub-hosted Linux runner instead of a CPU-limited edge/serverless request. Public repositories receive free standard-runner usage; private GitHub Free repositories have a 2,000-minute monthly allowance, so the hourly schedule consumes at least roughly 720 rounded job-minutes per 30-day month before active render time.
## Creative enrichment boundary

Campaign intake stores the unmodified brief and six fail-closed permissions in an
`EnrichmentControls` document; it does not ask normal users to curate an asset catalogue. The
planner searches reusable global/campaign Asset rows first and only then calls configured discovery
providers. Discovered objects enter the same private storage abstraction used by renders; the
database keeps provider identity, source, semantic metadata, media probe, licence, commercial-use
permission, attribution, restrictions and rights provenance. Planner eligibility checks both the
row and the backing object.

`rank_candidates → plan_enrichment → render → qa` is the durable path. One versioned Enrichment Plan exists for each candidate/clip version. It contains timestamped external or native events and measurable strategy features. The FFmpeg renderer materialises private objects only into disposable staging, composes audio/video sequentially, uploads the final clip, and records its verified URI and probe. Stateless worker loss therefore cannot erase the plan or output.

Human instructions are parsed into structured event changes. Asset-aware additions/replacements re-run eligibility and semantic selection; each change creates a new plan and child render while retaining the parent. Deterministic QA rechecks campaign permissions, bounds, insert limits, volume/ducking, licence/rights/attribution, object existence and final streams.

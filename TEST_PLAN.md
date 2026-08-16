# ALPHA — V0 Test Plan

## Test layers

### Unit
- schemas/validation;
- scoring;
- rule evaluation;
- signal calculations;
- policy versioning;
- edit instruction parsing;
- idempotency helpers.

### Integration
- DB + API;
- queue + worker;
- storage adapter;
- transcript/index;
- renderer;
- QA;
- email sink;
- approval gate.

### End-to-end
Happy path:
campaign -> sources -> research fixtures -> candidates -> render -> QA -> email -> review -> approve -> publication fixture -> performance -> feedback.

Failure paths:
- worker killed and resumed;
- duplicated source;
- playlist partially resolves;
- transcription failure and retry;
- mandatory watermark missing;
- research provider unavailable;
- publishing provider unavailable;
- duplicate publish retry;
- expired approval/review action.

## Critical invariants

1. Unapproved source cannot be published.
2. Unapproved clip cannot be posted.
3. Mandatory deterministic requirement failure blocks approval/publication.
4. Job can recover from worker death.
5. Completed stages are not needlessly repeated.
6. Publish retries cannot duplicate posts.
7. Review/edit history is immutable/traceable.
8. AI confidence/soft checks cannot masquerade as deterministic pass.
9. Raw research evidence remains distinct from derived labels.
10. Every ranked candidate has source/timestamp provenance.

## Research fixtures

Create a deterministic fixture dataset containing:
- several creators;
- creator baselines;
- normal posts;
- at least 3 clear relative outliers;
- one emerging semantic cluster;
- one high-view non-outlier from a huge account;
- one saturated topic;
- successful example clips with a common style pattern.

Tests should demonstrate that Alpha prefers true relative outliers over misleading raw-view totals.

## Render fixtures

Include:
- sample landscape source;
- sample portrait source;
- sample SRT/VTT;
- sample watermark PNG;
- expected ffprobe properties.

Do not distribute copyrighted third-party source footage in the repository unless licensed/allowed. Use generated or permissively licensed fixtures.

## Durability test

Simulate a long logical job:
- complete stages 0–3;
- kill worker;
- expire lease;
- start replacement worker;
- resume at stage 4;
- inject transient failure;
- retry;
- reach awaiting_review;
- verify no duplicated side effects.

The test does not need to run for 72 wall-clock hours. It must prove the architecture does not depend on a 72-hour-lived process.

## Implemented automated coverage (2026-08-13)

- `tests/test_api_e2e.py`: full fixture path, real FFmpeg renders, research outlier discrimination, evidence and style output, campaign-scoped account selection, pre-approval/wrong-account publish denial, natural-language child edit, approval, idempotent export, computed performance ratios, feedback taxonomy, one email and ledger policy provenance.
- `tests/test_api_e2e.py`: 25 approved sources + 25 examples and duplicate URL rejection.
- `tests/test_durability_and_rules.py`: four completed stages across short worker executions, abandoned lease aged by 73 hours, replacement worker, injected transient failure, persisted bounded backoff, separate attempt history, no duplicate completed stages/notification, active heartbeat and duplicate-worker exclusion during a long stage.
- `tests/test_durability_and_rules.py`: terminal failure emits exactly one secret-redacted attention email.
- `tests/test_durability_and_rules.py`: rights-attested local video/transcript import, duplicate detection, semantic source/timestamp search, real-source cut/render, output probe, deterministic QA and repeated-render checksum.
- `tests/test_durability_and_rules.py`: mandatory missing watermark fails QA and blocks approval/publication; an audited rule revision re-evaluates QA and permits approval.
- `tests/test_durability_and_rules.py`: deterministic pre-score control/treatment assignment, arm outcome summaries, experiment evaluation, audited policy activation and rollback.
- `tests/test_auth.py`: unauthenticated denial, failed/correct login, hashed session persistence, CSRF enforcement, authenticated write, logout and fail-closed configuration.
- `tests/test_research_import.py`: audited manual observations, AI-adapter query generation, expected relative outliers, cluster detection, creator profiles and raw/derived evidence separation.
- `tests/test_ops.py`: deployment diagnostics cover migrations, storage round-trip, FFmpeg and authentication configuration.
- `tests/test_email.py`: Resend payload/auth/idempotency contract, safe provider errors, automatic provider selection and fail-closed configuration.
- `tests/test_api_e2e.py`: review-ready email contains the campaign name, expanded source count, research summary, candidate count, clip count and review URL.
- `tests/test_live_providers.py`: YouTube playlist pagination/dedup, real metadata mapping, WebVTT timestamps, renewable caption OAuth contract, YouTube current-search evidence, TikTok oEmbed/approved Research API contracts, wider-web fallback/provenance and fail-closed live configuration.
- `tests/test_api_e2e.py`: rights-attested media links to an exact approved YouTube/playlist video ID and supplies the transcript/render asset for that source item.
- `tests/test_domain.py`: structured edit parsing/application and strict separation of AI-evaluated requirements from deterministic QA.
- `tests/test_external_persistence.py`: S3-compatible put/get/stream/materialise/delete contract, private bucket/key validation, disposable staging, real FFmpeg output recovered by a fresh adapter, Postgres URL/query-dialect selection and database state recovered after process-style reconstruction.

## Creative enrichment coverage

- `tests/test_enrichment.py`: campaign controls and raw brief, authorised music/meme/B-roll asset imports, licence/provenance and object-storage records.
- `tests/test_enrichment.py`: persisted planning produces one candidate with music, meme, B-roll and punch-in; real FFmpeg output is probed, streamed and deterministic QA-passed.
- `tests/test_enrichment.py`: the exact multi-action natural-language edit removes the meme, lowers music by 6 dB, adds a punch-in, renders a child, persists plan strategy features and leaves the parent byte-for-byte unchanged.
- `tests/test_enrichment.py`: prohibited, commercially disallowed, unlicensed and missing enrichment objects block deterministic QA.
- `tests/test_domain.py`: parsing and applying removal, volume, timing and native-event changes remains deterministic.

Manual review smoke should confirm the campaign controls, authorised-asset intake and timestamped enrichment timeline are legible on desktop/mobile before a production campaign.

## Pending credentialled acceptance

Automated contracts do not constitute live-provider completion. Before Build #2 is complete, execute one real campaign on the deployed service and retain evidence that:

1. a real playlist and individual video resolve through YouTube Data API v3;
2. accessible captions or exact-ID rights-attested transcript/media produce timestamped searchable segments;
3. provider events show real YouTube and public/approved research evidence without fixture rows;
4. the browser/laptop closes while the remote worker reaches `awaiting_review`;
5. Resend delivers the idempotent review email; and
6. the dashboard plays compliant clips and supports approve/change/reject.
7. Neon contains stage checkpoints/retries/review history after both app and worker instances restart; and
8. the final clip is still readable from R2 after the rendering worker and all local staging directories are gone.

## Manual UI smoke (2026-08-12)

In the in-app browser against the real local dev server:

1. Opened the protected dashboard and verified that an unauthenticated browser receives the login screen.
2. Signed in with the configured administrator and opened campaign intake.
3. Submitted two approved sources (one playlist), three successful examples, seeds, a selected manual-export account and configurable watermark requirements; the browser sent authenticated CSRF-protected writes.
4. Left the page idle while the durable worker progressed; reloaded to `awaiting_review` with three QA-passed variants and enabled approval actions.
5. Inspected source/timestamp, selection explanation, evidence IDs, score breakdown and compliance state.
6. Opened the populated Research Ledger and verified its recorded policy recommendation.

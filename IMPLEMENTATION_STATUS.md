# ALPHA — Implementation Status

Overall status: BUILD #2 NOT COMPLETE — LIVE ADAPTERS AND DEPLOYMENT ARE READY FOR CREDENTIALLED VALIDATION
Last updated: 2026-08-17

## Phase status

| Phase | Status | Notes |
|---|---|---|
| 0 Repository bootstrap | Complete | FastAPI package, migrations, local/Docker dev, seed, lint, tests, CI, health endpoint, README. |
| 1 Campaign intake | Complete | Create/edit/view API and responsive form; 25+ approved sources/examples tested; duplicate/URL validation; configurable watermark upload/storage; target-account selection and requirement classification. Submission immediately disables the action, exposes accessible live progress for creation/uploads/queueing, and restores a retryable form on failure. Partial setup failures identify the saved draft instead of inviting a duplicate submission. Drafts can be started later or permanently deleted with guarded database/object cleanup; submitted campaigns cannot be deleted. |
| 2 Durable worker system | Complete; production end-to-end run pending | Database-backed queue supports local SQLite and external Postgres. PostgreSQL acquisition uses transactional `FOR UPDATE SKIP LOCKED`; leases, heartbeats, retries, checkpoints, attempt history and recovery remain persisted. One bounded scheduled invocation can attempt the complete 12-stage campaign; the hourly trigger recovers retry-delayed or interrupted work instead of imposing three-stage waits. The dashboard reports queued/leased/retry/failed/checkpoint states, polls active campaigns automatically without a blocking overlay, and can explicitly requeue only terminal failures from their last checkpoint. SQLite durability/restart and query-dialect contracts are tested; the newly supplied Actions database secret still requires a successful production run. |
| 3 Source resolution/transcription | Live adapter implemented; credentialled validation blocked | `live` mode uses YouTube Data API v3 for real videos, paginated playlists and metadata, deduplicates video IDs across approved inputs, and uses authorised captions.list/download with timestamped WebVTT. Per-source failures are isolated and recorded. Caption download is officially limited to videos the OAuth user may edit; other approved videos require rights-attested media/transcript linked by exact YouTube ID. No YouTube credentials are present, so live API execution is not claimed. |
| 4 Successful-example intelligence | Live metadata enrichment implemented; credentialled validation blocked | Supplied YouTube examples use Data API metadata/statistics; supplied TikTok examples use official public oEmbed. Evidence is retained alongside heuristic style analysis. Instagram enrichment requires approved Graph access. |
| 5 Social research engine | Multi-source live adapter implemented; credentialled validation partial | Automatic YouTube search/statistics, optional approved TikTok Research API, optional Instagram professional-account hashtag research, TikTok oEmbed examples, GDELT with Google News RSS fallback, raw/derived separation and provider-event provenance. TikTok oEmbed and Google News RSS were exercised live; YouTube/TikTok Research/Instagram remain untested without credentials/approval. |
| 6 Strategy + source matching | Complete | Evidence-backed StrategyBrief, two discovery passes across every SourceItem, versioned weighted scores and approved-source provenance. |
| 7 Rendering + rule engine | Complete for rights-attested source and enrichment media | FFmpeg cuts imported source timestamps, converts to 9:16 H.264/AAC, and composes captions, watermark, authorised music/SFX/image/video inserts and native emphasis. Versioned evidence-backed Enrichment Plans precede renders; asset rights, campaign permissions, timings, object persistence and final streams are deterministic QA gates. Production staging is disposable and outputs use private object storage. Live mode refuses synthetic source stand-ins. |
| 8 QA + review dashboard | Complete | Video/evidence/score/style/compliance display plus timestamped enrichment timeline; approve/change/reject; deterministic failure blocks approval; audited rule revision re-evaluates QA and revokes invalid approvals; history retained. Every foreground API/upload wait is wrapped by an accessible reference-counted loading overlay with operation-specific status, while background status polling is non-blocking. Campaign, ledger, empty, media and fatal-error surfaces have explicit loading/error/retry states, and provider mode is labelled truthfully. |
| 9 Edit loop | Complete | Natural-language parser covers timing, caption/watermark/crop/headline/context plus removal, replacement, volume, extra B-roll, regenerated enrichment and native zoom requests; child renders/plans preserve parents. |
| 10 Email notification | Production-capable; live credentials pending | File sink plus Resend HTTPS adapter with provider idempotency, secret-safe failures and configuration diagnostics. Review-ready messages include campaign/source/research/candidate/clip counts and dashboard URL. Live delivery is not claimed until a Resend key and verified sender domain are supplied and exercised. |
| 11 Approval-gated publication | Complete for export fallback | Campaign-scoped connected accounts, approval and QA gates, approved-source/account rechecks, idempotent publication and manual export instructions. Live posting APIs are not configured. |
| 12 Feedback + performance | Complete | Human feedback and market snapshots remain independent; fixed reason taxonomy; computed revenue per clip/human-hour; disagreement API/dashboard signal. |
| 13 Research Ledger + experiments | Complete | Prediction policy recorded before outcome; deterministic control/treatment assignment before scoring; exploration allocation; arm outcome summaries; auditable activation and rollback. |
| 14 Operational hardening | £0-friendly stateless deployment active; live acceptance pending | The diskless Render service and scheduled GitHub Actions worker are active. External Postgres/S3 persistence, private streamed clip delivery and deployment diagnostics are implemented. The workflow now validates all production secrets before setup, rejects SQLite fallback, and attempts all 12 stages inside a 120-minute bound. App/worker restarts do not own durable files. A completed real campaign, persisted render and delivered review email are still required before browser-off acceptance is claimed. |
| 15 Creative enrichment | Complete locally; external catalogue licensing is user responsibility | Fail-closed campaign controls/raw brief, rights-aware Asset library/uploads, observed/inferred/unavailable research features, candidate suitability, semantic planner, FFmpeg composition, strategy tracking, enrichment QA/timeline and immutable natural-language edit loop are implemented. The realistic fixture renders music + meme + B-roll + punch-in and exercises the exact combined edit. No scraped or commercially restricted media is bundled. |

## Current work

Build #2 is deployed but is not complete. A production campaign was submitted and the Actions database secret has now been supplied; the next worker run must prove that it acquires the queued Postgres job and advances the full campaign. Do not mark Build #2 complete until real YouTube ingestion, remote continuation, persisted rendering, Resend delivery and review are observed.

## Last passing checks

- Scheduled-worker cost/latency correction (2026-08-17): removed the three-stage artificial stop, raised the bounded invocation to 120 minutes/12 stages, and added pre-install validation for external Postgres, object storage, YouTube, Resend and application URL secrets. The worker log now distinguishes an idle queue from a reached stage limit.
- `ruff check alpha tests`: passed (2026-08-17).
- `ruff format --check alpha tests`: passed (2026-08-17).
- `node --check web/app.js`: passed (2026-08-17).
- UI status smoke (2026-08-17): fixture server with its embedded worker disabled showed a submitted campaign as safely queued with automatic-continuation copy and no manual stage runner; a separate draft exposed Start processing/Delete draft; invalid API validation was readable; desktop/mobile component bounds and console errors were checked in the in-app browser.
- `pytest -q`: all 42 tests passed in one clean full-suite run (2026-08-17). Coverage includes campaign status polling, draft-only object cleanup, failed-stage requeue, campaign enrichment research/QA, review-command parsing, a localized freeze-frame renderer contract, and a real FFmpeg music + meme + B-roll + punch-in render followed by the exact immutable child edit. Existing external-persistence, live-provider, durability, authentication, email and deployment contracts remain passing.
- GitHub Actions CI diagnosis (2026-08-17): run `31981021312` exposed that the bundled Linux `imageio-ffmpeg` binary could not execute ALPHA's caption/watermark filter graph. CI, the scheduled worker and the production Docker image now install the distribution FFmpeg plus DejaVu fonts; the renderer retains `imageio-ffmpeg` only as a local fallback and surfaces bounded stderr on failure.
- Real public endpoint smoke (2026-08-13): TikTok official oEmbed returned real metadata; Google News RSS returned 100 current results; GDELT returned HTTP 429 and the fallback behaved as designed.
- Production observation (2026-08-17): the diskless Render UI submitted a durable Postgres job and the scheduled Actions workflow ran remotely. The old workflow exited successfully without acquiring it because its Actions `DATABASE_URL` was absent; the user has now supplied that secret, and the fail-fast/full-campaign correction awaits the next pushed workflow run.
- Authenticated in-app browser smoke: signed in, submitted a campaign with a selected export account, left the worker processing, reloaded to `awaiting_review` with three QA-passed variants, and opened the populated Research Ledger.
- FFmpeg: bundled `imageio-ffmpeg` executable used for fixture and rights-attested imported MP4 renders; actual resolution/audio/duration are probed by QA.

## Build #2 external blockers

1. Google Cloud: enable YouTube Data API v3 and provide `YOUTUBE_API_KEY`. For caption tracks on videos the user may edit, provide OAuth client/refresh credentials with `youtube.force-ssl`; the official API cannot download arbitrary third-party captions.
2. Rights-attested source media plus timestamped transcript for approved videos whose captions are not accessible through the authorised OAuth account. Link each upload to its exact YouTube video ID.
3. Verify the newly supplied GitHub Actions `DATABASE_URL` by observing the remote worker lease and checkpoint the queued production job.
4. Verify that the workflow's fail-fast check accepts the configured private R2 bucket, endpoint and scoped S3 credentials, then retain a rendered object across a worker restart.
5. Push and run the corrected scheduled workflow. Render and GitHub Actions are active; no persistent disk or paid Render plan is required.
6. Resend `RESEND_API_KEY` and `RESEND_FROM_EMAIL` at a verified domain.
7. Optional stronger platform coverage: approved TikTok Research Tools client key/secret and/or Instagram professional-account token/user ID. The automatic YouTube + public web/TikTok-example path does not depend on these optional approvals.
8. Real enrichment requires user-owned, public-domain or properly licensed campaign assets with commercial-use permission. The repository intentionally includes no third-party music, meme, reaction, stock-video or SFX catalogue and cannot grant those rights.

## External integrations requiring credentials

| Provider | Credential/approval | Configured | Fallback |
|---|---|---|---|
| YouTube | Data API key; OAuth refresh credentials with `youtube.force-ssl` for editable caption tracks | Adapter implemented; no credentials/live validation | Per-source recorded failure plus exact-ID rights-attested media/transcript |
| TikTok | Research Tools approval plus client key/secret (`research.data.basic`) | Research API + automatic client-token renewal implemented; no approval/credentials | Official public oEmbed for supplied TikTok examples |
| Instagram | Professional account, Graph access token and Instagram user ID | Hashtag research contract implemented; no credentials | Provider limitation recorded; YouTube/public-web research continues |
| Wider web | None | TikTok oEmbed and Google News RSS exercised live; GDELT returned HTTP 429 in this environment | Google News RSS fallback |
| Email | Resend sending-access API key + verified sender domain | Adapter implemented; live credentials absent | Idempotent file email sink |
| Database | Neon pooled Postgres `DATABASE_URL` | Production app is writing campaign/jobs; Actions secret supplied and awaiting worker acquisition proof | SQLite local/test adapter |
| Objects | R2 bucket endpoint/name/scoped access key/secret | S3-compatible adapter and restart persistence contract tested; live workflow validation pending | Local filesystem development adapter |
| Deployment | GitHub Actions secrets/enabled workflow + Render repository access | Diskless Render and scheduled Actions are active; real campaign completion pending | Local Docker/dev only; does not satisfy browser/laptop-off acceptance |
| Social publishing | Platform app approval + OAuth | No | Explicit-approval manual export package |

## Resume instructions

1. Read PRODUCT_BIBLE.md, BUILD_SPEC.md, ARCHITECTURE.md, AGENTS.md and DECISIONS.md.
2. Run `.\scripts\test.ps1` and verify this status against code.
3. Verify the production secret preflight, then manually dispatch the corrected worker.
4. Run one real authorised campaign and retain Postgres checkpoints, R2 clip URI, scheduled-worker runs, provider events, email ID and review evidence.
5. Do not claim Build #2 complete until that live acceptance test passes.

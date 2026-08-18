# ALPHA — Implementation Status

Overall status: BUILD #2 NOT COMPLETE — LIVE ADAPTERS AND DEPLOYMENT ARE READY FOR CREDENTIALLED VALIDATION
Last updated: 2026-08-18

## Phase status

| Phase | Status | Notes |
|---|---|---|
| 0 Repository bootstrap | Complete | FastAPI package, migrations, local/Docker dev, seed, lint, tests, CI, health endpoint, README. |
| 1 Campaign intake | Complete | Create/edit/view API and responsive form; 25+ approved sources/examples tested; duplicate/URL validation; configurable watermark upload/storage; target-account selection and requirement classification. Economics now store payout amount/currency/arbitrary qualified-view unit and optional rules. Per-source pasted transcript input and the six uncluttered enrichment permissions replace campaign-by-campaign asset-library fields. Submission immediately disables the action, exposes accessible live progress and restores a retryable form on failure. Drafts can be started later or permanently deleted; submitted campaigns cannot be deleted. |
| 2 Durable worker system | Complete; production end-to-end run pending | Database-backed queue supports local SQLite and external Postgres. PostgreSQL acquisition uses transactional `FOR UPDATE SKIP LOCKED`; leases, heartbeats, retries, checkpoints, attempt history and recovery remain persisted. One bounded scheduled invocation can attempt the complete 13-stage campaign; the hourly trigger recovers retry-delayed or interrupted work. `action_required` is a durable terminal/remediable state with an idempotent email. The dashboard reports persisted progress and requeue/remediation actions. |
| 3 Source resolution/transcription | Live adapter implemented; credentialled validation blocked | `live` mode uses YouTube Data API v3 for real videos, paginated playlists and metadata, deduplicates video IDs, and uses authorised captions.list/download with timestamped WebVTT. Sources also accept exact-linked pasted timestamped/plain transcripts and rights-attested video/audio. Uploads without transcript invoke a configured Whisper-compatible command. A pre-research checkpoint exposes metadata/transcript/media/research/render readiness and stops unusable campaigns as `ACTION REQUIRED`. YouTube/OAuth and a production transcription command are not available here, so live execution is not claimed. |
| 4 Successful-example intelligence | Live metadata enrichment implemented; credentialled validation blocked | Supplied YouTube examples use Data API metadata/statistics; supplied TikTok examples use official public oEmbed. Evidence is retained alongside heuristic style analysis. Instagram enrichment requires approved Graph access. |
| 5 Social research engine | Multi-source live adapter implemented; credentialled validation partial | Automatic YouTube search/statistics, optional approved TikTok Research API, optional Instagram professional-account hashtag research, TikTok oEmbed examples, GDELT with Google News RSS fallback, raw/derived separation and provider-event provenance. TikTok oEmbed and Google News RSS were exercised live; YouTube/TikTok Research/Instagram remain untested without credentials/approval. |
| 6 Strategy + source matching | Complete | Evidence-backed StrategyBrief, two discovery passes across every SourceItem, versioned weighted scores and approved-source provenance. If normal discovery returns zero, a broad compliant pass selects the strongest funny/surprising/controversial/emotional/story/useful/quotable moment; a genuinely empty corpus becomes `ACTION REQUIRED`. Expected value uses the campaign's actual payout unit. |
| 7 Rendering + rule engine | Complete for rights-attested source and enrichment media | FFmpeg cuts imported source timestamps, converts to 9:16 H.264/AAC, and composes captions, watermark, authorised music/SFX/image/video inserts and native emphasis. Versioned evidence-backed Enrichment Plans precede renders; asset rights, campaign permissions, timings, object persistence and final streams are deterministic QA gates. Production staging is disposable and outputs use private object storage. Live mode refuses synthetic source stand-ins. |
| 8 QA + review dashboard | Complete | Video/evidence/score/style/compliance display plus timestamped enrichment timeline; approve/change/reject; deterministic failure blocks approval; audited rule revision re-evaluates QA and revokes invalid approvals; history retained. Every foreground API/upload wait is wrapped by an accessible reference-counted loading overlay with operation-specific status, while background status polling is non-blocking. Campaign, ledger, empty, media and fatal-error surfaces have explicit loading/error/retry states, and provider mode is labelled truthfully. |
| 9 Edit loop | Complete | Natural-language parser covers timing, caption/watermark/crop/headline/context plus removal, replacement, volume, extra B-roll, regenerated enrichment and native zoom requests; child renders/plans preserve parents. |
| 10 Email notification | Production-capable; live credentials pending | File sink plus Resend HTTPS adapter with provider idempotency, secret-safe failures and configuration diagnostics. Review-ready messages include campaign/source/research/candidate/clip counts and dashboard URL. Live delivery is not claimed until a Resend key and verified sender domain are supplied and exercised. |
| 11 Approval-gated publication | Complete for export fallback | Campaign-scoped connected accounts, approval and QA gates, approved-source/account rechecks, idempotent publication and manual export instructions. Live posting APIs are not configured. |
| 12 Feedback + performance | Complete | Human feedback and market snapshots remain independent; fixed reason taxonomy; payout revenue is proportional to arbitrary qualified-view units with optional minimum, cap and whole-block rounding; computed revenue per clip/human-hour and disagreement API/dashboard signal. |
| 13 Research Ledger + experiments | Complete | Prediction policy recorded before outcome; deterministic control/treatment assignment before scoring; exploration allocation; arm outcome summaries; auditable activation and rollback. |
| 14 Operational hardening | £0-friendly stateless deployment active; live acceptance pending | The diskless Render service and scheduled GitHub Actions worker are active. External Postgres/S3 persistence, private streamed clip delivery and deployment diagnostics are implemented. The workflow validates production secrets, rejects SQLite fallback, and attempts all 13 stages inside a 120-minute bound. App/worker restarts do not own durable files. A completed real campaign, persisted render and delivered review email are still required before browser-off acceptance is claimed. |
| 15 Creative enrichment | Automatic discovery implemented; live catalogue validation pending | Six fail-closed permissions, research/moment-driven use/omission decisions, cache-first global Asset reuse, semantic matching and extensible discovery adapters are implemented. Openverse is filtered to CC0/PDM/CC BY/CC BY-SA commercial/modification-compatible images; Pexels photo/video is optional. Provider/source/licence/attribution/object provenance appears in the immutable plan/review timeline. Unsafe/unavailable assets are omitted without failing rendering. Existing admin import APIs remain for cached/user-owned assets but are absent from normal intake. |

## Current work

Build #2 remains deployed but not complete. The previous real job proved remote Postgres execution
and Resend failure delivery, then stopped at candidate ranking because its YouTube source had no
transcript. The new preflight/remediation workflow prevents that wasted research run, but this commit
must still be deployed and exercised with captions or exact-linked authorised media/transcript.

## Last passing checks

- Source/readiness, payout and automatic-asset milestone (2026-08-18): 13-stage preflighted pipeline, `ACTION REQUIRED` remediation/email, candidate fallback, cache-first provider discovery, command transcription and arbitrary payout units implemented. Full checks are recorded below after this increment's final verification.
- Real anonymous Openverse smoke (2026-08-18): the production adapter returned two filtered results for `surprised reaction`, carrying CC0/CC BY licence metadata. Download/cache/render contracts remain covered by deterministic tests; Pexels still needs a key for live validation.
- Scheduled-worker cost/latency correction (2026-08-17): removed the three-stage artificial stop, raised the bounded invocation to 120 minutes/13 stages, and added pre-install validation for external Postgres, object storage, YouTube, Resend and application URL secrets.
- Production workflow `32067208450` (2026-08-17): the corrected secret preflight and complete-campaign step passed on commit `a40b5d2`. The previously queued campaign had already advanced through seven checkpoints before failing at `rank_candidates`: one source item (`agKaAF51xW8`) had zero transcript segments, so discovery searched zero source items and produced no candidates. Resend accepted the idempotent failure notification. This is a source-input/access blocker, not a queued-worker stall.
- `ruff check alpha tests`: passed (2026-08-18).
- `ruff format --check alpha tests`: passed (2026-08-18).
- `node --check web/app.js`: passed (2026-08-18).
- UI status smoke (2026-08-17): fixture server with its embedded worker disabled showed a submitted campaign as safely queued with automatic-continuation copy and no manual stage runner; a separate draft exposed Start processing/Delete draft; invalid API validation was readable; desktop/mobile component bounds and console errors were checked in the in-app browser.
- `pytest -q`: all 52 tests passed in one clean full-suite run (2026-08-18). New coverage includes Openverse/Pexels discovery contracts, cache reuse and safe omission, pasted transcripts, background upload transcription, source preflight/action-required state, broad candidate fallback, arbitrary payout blocks/revenue and intake removal of manual asset fields. Existing external-persistence, live-provider, durability, authentication, email, rendering and deployment contracts remain passing.
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
8. Optional Pexels enrichment requires `PEXELS_API_KEY`; Openverse image/audio discovery can run anonymously but an `OPENVERSE_API_TOKEN` improves reliability. Provider licence metadata must still be reviewed for the intended use. If either catalogue has no safe match, the optional enrichment is omitted rather than fabricated.
9. Automatic upload transcription requires `ALPHA_TRANSCRIPTION_COMMAND` and its Whisper-compatible executable/model installed on every worker. Without it, supply a timestamped transcript with the authorised upload.

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
| Enrichment assets | Optional Openverse token; optional Pexels API key | Anonymous Openverse search exercised live; provider/download/cache contracts tested; Pexels not live-tested | Existing licensed cache, native edits, or safe omission |
| Transcription | Installed Whisper-compatible command/model configured in `ALPHA_TRANSCRIPTION_COMMAND` | Command contract tested with a fixture transcriber; no production command configured | Pasted timestamped transcript or accessible YouTube captions |
| Deployment | GitHub Actions secrets/enabled workflow + Render repository access | Diskless Render and scheduled Actions are active; real campaign completion pending | Local Docker/dev only; does not satisfy browser/laptop-off acceptance |
| Social publishing | Platform app approval + OAuth | No | Explicit-approval manual export package |

## Resume instructions

1. Read PRODUCT_BIBLE.md, BUILD_SPEC.md, ARCHITECTURE.md, AGENTS.md and DECISIONS.md.
2. Run `.\scripts\test.ps1` and verify this status against code.
3. Verify the production secret preflight, then manually dispatch the corrected worker.
4. Run one real authorised campaign and retain Postgres checkpoints, R2 clip URI, scheduled-worker runs, provider events, email ID and review evidence.
5. Do not claim Build #2 complete until that live acceptance test passes.

# ALPHA — Implementation Status

Overall status: BUILD #2 NOT COMPLETE — LIVE ADAPTERS AND DEPLOYMENT ARE READY FOR CREDENTIALLED VALIDATION
Last updated: 2026-08-13

## Phase status

| Phase | Status | Notes |
|---|---|---|
| 0 Repository bootstrap | Complete | FastAPI package, migrations, local/Docker dev, seed, lint, tests, CI, health endpoint, README. |
| 1 Campaign intake | Complete | Create/edit/view API and responsive form; 25+ approved sources/examples tested; duplicate/URL validation; configurable watermark upload/storage; target-account selection and requirement classification. |
| 2 Durable worker system | Complete | SQLite queue, atomic leasing, active lease renewal, persisted exponential retry scheduling, per-attempt history, terminal-failure notification, checkpoints, expired-lease recovery and idempotent stages. Long-stage contention and restart/73-hour-expiry simulations are tested. |
| 3 Source resolution/transcription | Live adapter implemented; credentialled validation blocked | `live` mode uses YouTube Data API v3 for real videos, paginated playlists and metadata, deduplicates video IDs across approved inputs, and uses authorised captions.list/download with timestamped WebVTT. Per-source failures are isolated and recorded. Caption download is officially limited to videos the OAuth user may edit; other approved videos require rights-attested media/transcript linked by exact YouTube ID. No YouTube credentials are present, so live API execution is not claimed. |
| 4 Successful-example intelligence | Live metadata enrichment implemented; credentialled validation blocked | Supplied YouTube examples use Data API metadata/statistics; supplied TikTok examples use official public oEmbed. Evidence is retained alongside heuristic style analysis. Instagram enrichment requires approved Graph access. |
| 5 Social research engine | Multi-source live adapter implemented; credentialled validation partial | Automatic YouTube search/statistics, optional approved TikTok Research API, optional Instagram professional-account hashtag research, TikTok oEmbed examples, GDELT with Google News RSS fallback, raw/derived separation and provider-event provenance. TikTok oEmbed and Google News RSS were exercised live; YouTube/TikTok Research/Instagram remain untested without credentials/approval. |
| 6 Strategy + source matching | Complete | Evidence-backed StrategyBrief, two discovery passes across every SourceItem, versioned weighted scores and approved-source provenance. |
| 7 Rendering + rule engine | Complete for rights-attested source media | FFmpeg cuts imported source timestamps, converts to 9:16 H.264/AAC, burns captions/headlines, applies uploaded/generated watermark controls, probes output and records render lineage. Live mode refuses to render a synthetic stand-in and requires media linked to the exact approved YouTube video ID. |
| 8 QA + review dashboard | Complete | Video/evidence/score/style/compliance display; approve/change/reject; deterministic failure blocks approval; audited rule revision re-evaluates QA and revokes invalid approvals; history retained. |
| 9 Edit loop | Complete | Natural-language parser covers timing, caption/watermark size/position, crop, headline and context; child renders preserve parents. |
| 10 Email notification | Production-capable; live credentials pending | File sink plus Resend HTTPS adapter with provider idempotency, secret-safe failures and configuration diagnostics. Review-ready messages include campaign/source/research/candidate/clip counts and dashboard URL. Live delivery is not claimed until a Resend key and verified sender domain are supplied and exercised. |
| 11 Approval-gated publication | Complete for export fallback | Campaign-scoped connected accounts, approval and QA gates, approved-source/account rechecks, idempotent publication and manual export instructions. Live posting APIs are not configured. |
| 12 Feedback + performance | Complete | Human feedback and market snapshots remain independent; fixed reason taxonomy; computed revenue per clip/human-hour; disagreement API/dashboard signal. |
| 13 Research Ledger + experiments | Complete | Prediction policy recorded before outcome; deterministic control/treatment assignment before scoring; exploration allocation; arm outcome summaries; auditable activation and rollback. |
| 14 Operational hardening | Deployable single-instance configuration; deployment blocked | Render Blueprint runs API + durable worker in one container against an encrypted persistent disk, matching SQLite's single-host boundary. The paid starter tier is intentional because free Render web services cannot attach persistent disks. No Render account/session exists here, so no remote service or browser-off acceptance test has been run. |

## Current work

Build #2 code/configuration is ready for credentialled validation but is not complete. The next action is to supply the external credentials below, create the Render Blueprint, and run one real authorised campaign end to end. Do not mark Build #2 complete until real YouTube ingestion, remote continuation, Resend delivery and review are observed.

## Last passing checks

- `ruff check alpha tests`: passed (2026-08-12).
- `ruff format --check alpha tests`: passed (2026-08-12).
- `node --check web/app.js`: passed (2026-08-12).
- `pytest`: 30 passed in 344.64s (2026-08-13), preserving the prior 19 tests and adding live-provider, renewable OAuth/client-token, per-source failure, public fallback, metadata-derived example analysis and exact-ID authorised-media coverage.
- Real public endpoint smoke (2026-08-13): TikTok official oEmbed returned real metadata; Google News RSS returned 100 current results; GDELT returned HTTP 429 and the fallback behaved as designed.
- Cloud entry-point smoke (2026-08-13): `python -m alpha.cloud` started API + worker and `/api/health` reported nine applied migrations; the process was then stopped cleanly. `render.yaml` parsed with the required Docker service and persistent-disk fields.
- Authenticated in-app browser smoke: signed in, submitted a campaign with a selected export account, left the worker processing, reloaded to `awaiting_review` with three QA-passed variants, and opened the populated Research Ledger.
- FFmpeg: bundled `imageio-ffmpeg` executable used for fixture and rights-attested imported MP4 renders; actual resolution/audio/duration are probed by QA.

## Build #2 external blockers

1. Google Cloud: enable YouTube Data API v3 and provide `YOUTUBE_API_KEY`. For caption tracks on videos the user may edit, provide OAuth client/refresh credentials with `youtube.force-ssl`; the official API cannot download arbitrary third-party captions.
2. Rights-attested source media plus timestamped transcript for approved videos whose captions are not accessible through the authorised OAuth account. Link each upload to its exact YouTube video ID.
3. Render account with GitHub repository access and billing approval for the starter web service plus 10 GB persistent disk; no Render login/API key exists in this environment.
4. Resend `RESEND_API_KEY` and `RESEND_FROM_EMAIL` at a verified domain.
5. Optional stronger platform coverage: approved TikTok Research Tools client key/secret and/or Instagram professional-account token/user ID. The automatic YouTube + public web/TikTok-example path does not depend on these optional approvals.

## External integrations requiring credentials

| Provider | Credential/approval | Configured | Fallback |
|---|---|---|---|
| YouTube | Data API key; OAuth refresh credentials with `youtube.force-ssl` for editable caption tracks | Adapter implemented; no credentials/live validation | Per-source recorded failure plus exact-ID rights-attested media/transcript |
| TikTok | Research Tools approval plus client key/secret (`research.data.basic`) | Research API + automatic client-token renewal implemented; no approval/credentials | Official public oEmbed for supplied TikTok examples |
| Instagram | Professional account, Graph access token and Instagram user ID | Hashtag research contract implemented; no credentials | Provider limitation recorded; YouTube/public-web research continues |
| Wider web | None | TikTok oEmbed and Google News RSS exercised live; GDELT returned HTTP 429 in this environment | Google News RSS fallback |
| Email | Resend sending-access API key + verified sender domain | Adapter implemented; live credentials absent | Idempotent file email sink |
| Deployment | Render account + GitHub access + paid persistent-disk service approval | `render.yaml` complete; not deployed | Local Docker/dev only; does not satisfy browser/laptop-off acceptance |
| Social publishing | Platform app approval + OAuth | No | Explicit-approval manual export package |

## Resume instructions

1. Read PRODUCT_BIBLE.md, BUILD_SPEC.md, ARCHITECTURE.md, AGENTS.md and DECISIONS.md.
2. Run `.\scripts\test.ps1` and verify this status against code.
3. Supply the Build #2 credentials and create the Render Blueprint from `render.yaml`.
4. Run one real authorised campaign and retain provider events, email ID and remote worker evidence.
5. Do not claim Build #2 complete until that live acceptance test passes.

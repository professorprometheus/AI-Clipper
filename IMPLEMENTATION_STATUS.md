# ALPHA — Implementation Status

Overall status: FUNCTIONAL SINGLE-USER V0 WITH AUTHORISED IMPORTS; LIVE PLATFORM ADAPTERS NOT ENABLED
Last updated: 2026-08-12

## Phase status

| Phase | Status | Notes |
|---|---|---|
| 0 Repository bootstrap | Complete | FastAPI package, migrations, local/Docker dev, seed, lint, tests, CI, health endpoint, README. |
| 1 Campaign intake | Complete | Create/edit/view API and responsive form; 25+ approved sources/examples tested; duplicate/URL validation; configurable watermark upload/storage; target-account selection and requirement classification. |
| 2 Durable worker system | Complete | SQLite queue, atomic leasing, active lease renewal, persisted exponential retry scheduling, per-attempt history, terminal-failure notification, checkpoints, expired-lease recovery and idempotent stages. Long-stage contention and restart/73-hour-expiry simulations are tested. |
| 3 Source resolution/transcription | Complete for fixture/authorised-import path | Playlist expansion, rights-attested local video imports, validated timestamped transcripts, local embeddings, all-source retrieval and semantic search returning source/timestamps. Live YouTube remains external-access work. |
| 4 Successful-example intelligence | Complete for fixture/manual path | Structured fields, evidence/confidence-bearing StyleProfile and retained raw example records. |
| 5 Social research engine | Complete for fixture/manual path | AI-adapter query generation, audited manual observation imports, raw/derived separation, creator profiles, relative outliers, velocity, clustering, lifecycle/saturation proxies and evidence citations. Live APIs remain external-access work. |
| 6 Strategy + source matching | Complete | Evidence-backed StrategyBrief, two discovery passes across every SourceItem, versioned weighted scores and approved-source provenance. |
| 7 Rendering + rule engine | Complete for generated and imported authorised media | FFmpeg cuts imported source timestamps, converts to 9:16 H.264/AAC, burns captions/headlines, applies uploaded/generated watermark controls, probes output and records render lineage. Repeat renders are byte-stable in the tested environment. |
| 8 QA + review dashboard | Complete | Video/evidence/score/style/compliance display; approve/change/reject; deterministic failure blocks approval; audited rule revision re-evaluates QA and revokes invalid approvals; history retained. |
| 9 Edit loop | Complete | Natural-language parser covers timing, caption/watermark size/position, crop, headline and context; child renders preserve parents. |
| 10 Email notification | Complete for development sink | Provider abstraction; exactly-once review-ready and terminal-failure messages; secret-redacted content and correct campaign URLs. Production SMTP/API adapter is not configured. |
| 11 Approval-gated publication | Complete for export fallback | Campaign-scoped connected accounts, approval and QA gates, approved-source/account rechecks, idempotent publication and manual export instructions. Live posting APIs are not configured. |
| 12 Feedback + performance | Complete | Human feedback and market snapshots remain independent; fixed reason taxonomy; computed revenue per clip/human-hour; disagreement API/dashboard signal. |
| 13 Research Ledger + experiments | Complete | Prediction policy recorded before outcome; deterministic control/treatment assignment before scoring; exploration allocation; arm outcome summaries; auditable activation and rollback. |
| 14 Operational hardening | Complete for single-user V0 | Structured logs, retry classification, rate limiting, hashed expiring sessions, CSRF protection, optional API token, fail-closed auth configuration, audit log, safe cleanup, backup/restore, deployment doctor, licence review and CI. Multi-host deployment and an external identity provider are production extensions. |

## Current work

The vertically complete single-user V0 is implemented and tested with fixture providers and rights-attested local media/research imports. The next production increment is a permitted live YouTube/source provider plus approved social/email/publishing adapters. PostgreSQL and an external identity provider are required before multi-host production deployment.

## Last passing checks

- `ruff check alpha tests`: passed (2026-08-12).
- `ruff format --check alpha tests`: passed (2026-08-12).
- `node --check web/app.js`: passed (2026-08-12).
- `pytest`: 15 passed in 231.12s (2026-08-12), including durability, auth/CSRF, imports, real media, experiment, publication and operations coverage.
- Authenticated in-app browser smoke: signed in, submitted a campaign with a selected export account, left the worker processing, reloaded to `awaiting_review` with three QA-passed variants, and opened the populated Research Ledger.
- FFmpeg: bundled `imageio-ffmpeg` executable used for fixture and rights-attested imported MP4 renders; actual resolution/audio/duration are probed by QA.

## Blockers

No blocker to the functional local/CI V0.

Production/live limitations are external-access or deployment work and are not represented as complete integrations:

- permitted YouTube metadata/playlist/transcript and authorised media access;
- platform-approved live social research APIs/data imports;
- SMTP/API email credentials and production adapter;
- platform posting approval/OAuth and supported posting adapters;
- production external identity provider, PostgreSQL/multi-host validation and deployment secret manager.

The implemented fixture/manual adapters and approval-gated export remain the documented fallback for each unavailable live path.

## External integrations requiring credentials

| Provider | Credential/approval | Configured | Fallback |
|---|---|---|---|
| YouTube | API key/OAuth and content access rights as applicable | No | Fixture resolver plus rights-attested local video/transcript import |
| Social research platforms | Approved API/data access | No | Deterministic fixture plus audited observation imports |
| Email | SMTP/API credentials | No | Idempotent file email sink |
| Social publishing | Platform app approval + OAuth | No | Explicit-approval manual export package |

## Resume instructions

1. Read PRODUCT_BIBLE.md, BUILD_SPEC.md, ARCHITECTURE.md, AGENTS.md and DECISIONS.md.
2. Run `.\scripts\test.ps1` and verify this status against code.
3. Continue with a permitted live source/provider adapter; do not download material without rights.
4. Preserve provider boundaries and fixture/manual paths while adding live implementations.
5. Do not claim a live adapter complete until exercised against that live provider.

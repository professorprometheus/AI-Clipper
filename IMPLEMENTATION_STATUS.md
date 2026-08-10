# ALPHA — Implementation Status

Overall status: FUNCTIONAL V0 FIXTURE/DEVELOPMENT FLOW; LIVE PLATFORM ADAPTERS NOT ENABLED
Last updated: 2026-08-10

## Phase status

| Phase | Status | Notes |
|---|---|---|
| 0 Repository bootstrap | Complete | FastAPI package, migrations, local/Docker dev, seed, lint, tests, CI, health endpoint, README. |
| 1 Campaign intake | Complete | Create/edit/view API and responsive form; 25+ approved sources/examples tested; duplicate/URL validation; configurable watermark upload/storage; requirement classification. |
| 2 Durable worker system | Complete | SQLite queue, atomic leasing, heartbeats, checkpoints, retry, expired-lease recovery and idempotent stages. Restart/73-hour-expiry simulation tested. |
| 3 Source resolution/transcription | Complete for fixture/manual path | Playlist expansion, timestamped transcript chunks, local embeddings and all-source retrieval. Live YouTube adapter remains external-access work. |
| 4 Successful-example intelligence | Complete for fixture/manual path | Structured fields, evidence/confidence-bearing StyleProfile and retained raw example records. |
| 5 Social research engine | Complete for fixture/manual path | Provider contract, raw/derived separation, relative outliers, velocity, clustering, lifecycle/saturation proxies and evidence citations. Live APIs remain external-access work. |
| 6 Strategy + source matching | Complete | Evidence-backed StrategyBrief, two discovery passes across every SourceItem, versioned weighted scores and approved-source provenance. |
| 7 Rendering + rule engine | Complete for generated/authorised fixture media | FFmpeg 9:16 H.264/AAC rendering, burned captions, uploaded/generated watermark controls, render lineage and deterministic QA. Authorised live source-media acquisition needs a provider. |
| 8 QA + review dashboard | Complete | Video/evidence/score/style/compliance display; approve/change/reject; deterministic failure blocks approval; history retained. |
| 9 Edit loop | Complete | Natural-language parser covers timing, caption/watermark size/position, crop, headline and context; child renders preserve parents. |
| 10 Email notification | Complete for development sink | Provider abstraction and exactly-once file email with campaign review URL. Production SMTP/API adapter not configured. |
| 11 Approval-gated publication | Complete for export fallback | Approval and QA gates, approved-source recheck, idempotent publication, manual export instructions. Live posting APIs not configured. |
| 12 Feedback + performance | Complete | Human feedback and market snapshots remain independent; revenue/human-time supported; disagreement API/dashboard signal implemented. |
| 13 Research Ledger + experiments | Complete | Prediction policy recorded before outcome; hypotheses, control/treatment, exploration allocation, evaluated outcomes, auditable activation and rollback. |
| 14 Operational hardening | Substantially complete for single-user V0 | Structured stage logs, retry classification, optional API token, rate limiting, audit log, safe cleanup, backup/restore notes, licence review and CI. Production OAuth/session management and distributed deployment validation remain. |

## Current work

The vertically complete local fixture V0 is implemented and tested. The first next production task is an authorised real source/media import adapter (or permitted YouTube API implementation), followed by authenticated deployment configuration.

## Last passing checks

- `ruff check alpha tests`: passed (2026-08-10).
- `pytest`: 7 passed in 61.08s (2026-08-10; after final uploaded-asset/caption hardening).
- End-to-end seed: completed all 11 worker stages to `awaiting_review`.
- In-app browser smoke: campaign form submitted; background worker completed after the page was left idle; three playable variants displayed; approval exposed manual export; Research Ledger displayed; zero browser console errors.
- FFmpeg: bundled `imageio-ffmpeg` executable used for actual MP4 fixture renders.

## Blockers

No blocker to the functional local/CI V0.

Production/live limitations are external-access or deployment work and are not represented as complete integrations:

- permitted YouTube metadata/playlist/transcript and authorised media access;
- platform-approved live social research APIs/data imports;
- SMTP/API email credentials and production adapter;
- platform posting approval/OAuth and supported posting adapters;
- production identity/session provider and deployment secret manager.

The implemented fixture/manual adapters and approval-gated export remain the documented fallback for each unavailable live path.

## External integrations requiring credentials

| Provider | Credential/approval | Configured | Fallback |
|---|---|---|---|
| YouTube | API key/OAuth and content access rights as applicable | No | Fixture resolver plus manual authorised import boundary |
| Social research platforms | Approved API/data access | No | Deterministic research fixture/manual imports |
| Email | SMTP/API credentials | No | Idempotent file email sink |
| Social publishing | Platform app approval + OAuth | No | Explicit-approval manual export package |

## Resume instructions

1. Read PRODUCT_BIBLE.md, BUILD_SPEC.md, ARCHITECTURE.md, AGENTS.md and DECISIONS.md.
2. Run `.\scripts\test.ps1` and verify this status against code.
3. Continue with the authorised source/media import adapter; do not download material without rights.
4. Preserve provider boundaries and fixture/manual paths while adding live implementations.
5. Do not claim a live adapter complete until exercised against that live provider.

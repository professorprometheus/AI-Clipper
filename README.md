# ALPHA V0

ALPHA is a research-led clipping system. A campaign contains many approved source URLs, successful example clips, research seeds, economics, branding, and deterministic/AI-evaluated requirements. A durable database-backed worker researches, resolves and indexes every approved source, ranks timestamped moments with evidence, renders clips, blocks deterministic failures, emails a review link, preserves edits, and creates a publication export only after explicit human approval.

The default path is local and free: SQLite, local files, generated authorised media, fixture research, a file email sink, and a manual publication export. No browser connection is needed after campaign submission.

## Quick start (Windows)

Prerequisite: Python 3.11+.

```powershell
.\scripts\dev.ps1
```

Open <http://127.0.0.1:8000>. The command creates `.venv`, installs dependencies, starts the API, and runs the durable worker in a background thread for development. Production-style operation uses separate processes:

```powershell
.\.venv\Scripts\python.exe -m uvicorn alpha.main:app --host 0.0.0.0 --port 8000
.\.venv\Scripts\python.exe -m alpha.worker
```

Or run the separated API/worker stack with `docker compose up --build`.

## Test and demo

```powershell
.\scripts\test.ps1
.\.venv\Scripts\python.exe -m alpha.seed
```

The tests render synthetic clips with bundled FFmpeg and demonstrate campaign → durable processing → multiple sources → example/style analysis → social evidence → candidate ranking → rendering/QA → notification/review/edit → approval → idempotent export → performance/feedback → Research Ledger.

Run deployment diagnostics before operating a fresh environment:

```powershell
.\.venv\Scripts\python.exe -m alpha.ops doctor
```

## Provider modes and external access

`ALPHA_PROVIDER_MODE=fixture` is the deterministic CI/demo path. `manual` retains the audited import-only path. `live` selects the production-capable provider set and fails startup unless `YOUTUBE_API_KEY` exists.

Live mode provides:

- YouTube Data API v3 video metadata, paginated playlist expansion, cross-input video-ID deduplication, current YouTube search/statistics and exact source provenance.
- YouTube captions.list/download through OAuth refresh credentials for caption tracks the OAuth user is permitted to edit. The official API does not allow arbitrary third-party caption downloads.
- Official TikTok public oEmbed enrichment for supplied examples and the approved TikTok Research API when its token is configured.
- Instagram professional-account hashtag research when its Graph token/user ID are configured.
- Public GDELT news signals with Google News RSS fallback; these are explicitly labelled mention signals, not social engagement metrics.
- Per-source/query provider events so partial failures and access limitations remain visible in `/api/campaigns/{id}/research`.
- Production email uses Resend when configured; without credentials V0 writes idempotent messages to `data/emails`.
- Direct posting needs each platform's approved posting API and OAuth credentials; V0 creates an approval-gated manual export instead.

No adapter may bypass access controls, CAPTCHA, or platform terms.

For real rendering, upload media you are authorised to process and supply its exact timestamped transcript. Enter one YouTube video ID per selected file to link the media to an individual approved video or an item inside an approved playlist. Live mode refuses to substitute generated fixture footage when authorised source media is absent.

## Configuration

Copy `.env.example` values into the process environment. Important settings:

- `ALPHA_DATABASE_PATH`: SQLite database path.
- `ALPHA_STORAGE_PATH`: watermarks, rendered clips, and export packages.
- `ALPHA_EMAIL_SINK_PATH`: development email messages.
- `ALPHA_EMAIL_PROVIDER`: `auto` (Resend when a key exists, otherwise file), `resend`, or `file`.
- `RESEND_API_KEY`: a Resend sending-access API key.
- `RESEND_FROM_EMAIL`: sender name/address at a verified Resend domain.
- `ALPHA_PROVIDER_MODE`: `fixture`, `manual`, or `live`.
- `YOUTUBE_API_KEY`: Google Cloud YouTube Data API v3 key; required by live mode.
- `YOUTUBE_OAUTH_CLIENT_ID`, `YOUTUBE_OAUTH_CLIENT_SECRET`, `YOUTUBE_OAUTH_REFRESH_TOKEN`: durable caption authorization using the `youtube.force-ssl` scope. The account must have permission to edit the requested caption tracks.
- `YOUTUBE_OAUTH_ACCESS_TOKEN`: optional short-lived caption token for temporary testing only.
- `TIKTOK_CLIENT_KEY` / `TIKTOK_CLIENT_SECRET`: optional approved TikTok Research Tools client; ALPHA renews the two-hour client token automatically. `TIKTOK_RESEARCH_ACCESS_TOKEN` is only a short-lived testing override.
- `INSTAGRAM_ACCESS_TOKEN` / `INSTAGRAM_USER_ID`: optional Instagram professional-account Graph access.
- `ALPHA_RESEARCH_REGION`, `ALPHA_RESEARCH_LOOKBACK_DAYS`, `ALPHA_RESEARCH_RESULTS_PER_QUERY`: live research bounds.
- `ALPHA_API_TOKEN`: optional API token required through `X-Alpha-Token` when configured.
- `ALPHA_LEASE_SECONDS`: worker lease duration; expired leases are recoverable.
- `ALPHA_RETRY_BASE_SECONDS` / `ALPHA_MAX_JOB_ATTEMPTS`: persisted retry policy.
- `ALPHA_REQUIRE_AUTH`: require browser sessions and protected API access.
- `ALPHA_ADMIN_EMAIL` / `ALPHA_ADMIN_PASSWORD`: required when auth is enabled.
- `ALPHA_SESSION_HOURS`: session lifetime.
- `ALPHA_COOKIE_SECURE`: set `true` whenever the site is served over HTTPS.

Secrets must be supplied through environment/deployment secret management and must never be committed or logged.

When authentication is enabled, the UI uses a hashed, expiring server-side session, an HttpOnly SameSite cookie and CSRF protection for unsafe methods. Startup fails closed if administrator credentials are missing. This is a single-admin V0 boundary, not a substitute for a production multi-user identity provider.

### Resend setup

1. Add and verify a domain in the [Resend dashboard](https://resend.com/docs/dashboard/domains/introduction).
2. Create a sending-access API key and store it as `RESEND_API_KEY`.
3. Set `RESEND_FROM_EMAIL`, for example `ALPHA <notifications@updates.example.com>`.
4. Leave `ALPHA_EMAIL_PROVIDER=auto` or set it explicitly to `resend`.
5. Run `python -m alpha.ops doctor`; its email check reports readiness without printing the key.

Review-ready messages include the campaign name, sources analysed, research summary, candidates considered, clips produced and review URL. ALPHA supplies its durable notification key to Resend's [idempotency header](https://resend.com/docs/dashboard/emails/idempotency-keys). The file adapter remains the credential-free local/CI fallback.

## Remote deployment

[`render.yaml`](./render.yaml) defines one Docker web service running `python -m alpha.cloud`: the authenticated API and a durable worker share one SQLite database and media volume. This is intentionally a single instance because SQLite is not a distributed queue.

Render's free web tier cannot attach a persistent disk, so the Blueprint uses the starter service plus a 10 GB encrypted persistent disk. Creating it requires:

1. Push this repository to GitHub and sign in to Render with repository access.
2. In Render, select **New → Blueprint**, choose this repository, and approve `render.yaml`.
3. Supply the required Blueprint secrets: `ALPHA_ADMIN_EMAIL`, `ALPHA_ADMIN_PASSWORD`, `YOUTUBE_API_KEY`, `RESEND_API_KEY`, and `RESEND_FROM_EMAIL`.
4. For officially accessible captions, also supply the three `YOUTUBE_OAUTH_*` refresh credentials. TikTok Research and Instagram variables are optional and require their respective platform approvals.
5. After deployment, run the service's diagnostics command `python -m alpha.ops doctor`, open `/api/health`, and execute the real campaign acceptance test before treating Build #2 as complete.

`ALPHA_BASE_URL` automatically falls back to Render's `RENDER_EXTERNAL_URL`, so review emails point to the deployed dashboard.

## Durable processing model

Each worker acquisition leases exactly one stage and actively renews that lease while the stage runs. The output and completed-stage checkpoint are committed before the next stage is queued. A killed worker's lease expires and another worker resumes the same stage; stale workers cannot commit after losing their token. Retry availability, exponential backoff and every attempt are persisted, while completed side effects are protected by stable uniqueness/idempotency keys. Logical jobs can therefore span many worker executions and do not assume one process lives for 72 hours.

## Approval and compliance invariants

- Only `SourceItem` records descended from the campaign's `ApprovedSource` set can become candidates.
- Deterministic and AI-evaluated QA are stored separately.
- A mandatory deterministic failure blocks approval and publication.
- Audited requirement revisions preserve the old value and trigger QA re-evaluation; invalidated approvals are revoked.
- Publication requires a persisted approval record and an idempotency key.
- Publication must use an enabled connected account selected by that campaign.
- Change requests create child variants; parent renders and review history remain intact.
- Prediction scores and the strategy policy version are recorded before outcomes.

## Backup, restore, and retention

Create a consistent SQLite backup:

```powershell
.\.venv\Scripts\python.exe -m alpha.ops backup --destination backups\alpha.db
```

Restore by stopping API/workers, preserving the current database, copying the validated backup to `ALPHA_DATABASE_PATH`, then starting one API instance and checking `/api/health` before workers. Object storage must be backed up/restored alongside the database because records reference local file paths.

Retention cleanup is dry-run by default and only targets generated `.ppm`/manifest render intermediates, never source assets, final MP4s, uploads, evidence, or history:

```powershell
.\.venv\Scripts\python.exe -m alpha.ops cleanup --older-than-days 30
.\.venv\Scripts\python.exe -m alpha.ops cleanup --older-than-days 30 --apply
```

## Repository map

- `alpha/main.py`: FastAPI endpoints and static dashboard.
- `alpha/pipeline.py`: leased queue and resumable campaign stages.
- `alpha/services.py`: campaign, review, publication, feedback, and experiment use cases.
- `alpha/domain.py`: scoring, signals, edit parsing, and deterministic QA.
- `alpha/providers.py`: compliant provider abstractions and local/fixture adapters.
- `alpha/live_providers.py`: official/permitted YouTube, TikTok, Instagram and wider-web provider clients.
- `alpha/cloud.py`: single-instance remote API + durable worker entry point.
- `render.yaml`: persistent Render deployment Blueprint.
- `migrations/`: additive SQLite schema.
- `web/`: responsive review dashboard.
- `tests/`: unit, API, durability, invariant, and end-to-end coverage.

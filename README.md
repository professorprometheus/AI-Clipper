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
- `DATABASE_URL`: production Postgres connection string; takes precedence over `ALPHA_DATABASE_PATH`. Use the pooled Neon URL with TLS enabled.
- `ALPHA_STORAGE_PROVIDER`: `local` for development or `s3` for production.
- `S3_ENDPOINT_URL`, `S3_REGION`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`: private S3-compatible object storage. For R2, use the account S3 endpoint and region `auto`.
- `ALPHA_RUN_EMBEDDED_WORKER`: leave `true` locally; the Render Blueprint sets `false` because scheduled compute owns production work.
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

[`render.yaml`](./render.yaml) defines a diskless Render Free web service. It may sleep after inactivity: all state is external, and [`.github/workflows/alpha-worker.yml`](./.github/workflows/alpha-worker.yml) wakes a fresh worker hourly to run the complete 12-stage campaign within a bounded 120-minute invocation. `workflow_dispatch` provides an immediate first invocation. If an invocation is interrupted, its persisted checkpoint lets the next hourly or manual invocation resume it. No Render persistent disk or continuously awake process is required.

### 1. Create the free persistence services

1. Create a [Neon Free project](https://neon.com/pricing). Copy its **pooled** Postgres connection string, including `sslmode=require`, as `DATABASE_URL`. Free currently includes 0.5 GB storage and 100 CU-hours per project; compute scales to zero when idle.
2. In Cloudflare, [enable R2](https://developers.cloudflare.com/r2/get-started/), create a **Standard** bucket, then create an R2 S3 API token scoped read/write to only that bucket. Record:
   - `S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com`
   - `S3_REGION=auto`
   - `S3_BUCKET=<bucket-name>`
   - `S3_ACCESS_KEY_ID=<token access key>`
   - `S3_SECRET_ACCESS_KEY=<token secret>`
3. R2 requires completing its subscription/checkout flow, but its [Standard free allowance](https://developers.cloudflare.com/r2/pricing/) is currently 10 GB-month, 1 million Class A writes, 10 million Class B reads and free egress. Set a billing notification/limit appropriate to the account.

### 2. Deploy the sleeping web application

1. Push the repository to GitHub. In Render, choose **New → Blueprint**, connect the repository, and approve `render.yaml`.
2. Enter every `sync: false` value requested by the Blueprint:
   - `ALPHA_ADMIN_EMAIL`
   - `ALPHA_ADMIN_PASSWORD`
   - `DATABASE_URL`
   - `S3_ENDPOINT_URL`
   - `S3_BUCKET`
   - `S3_ACCESS_KEY_ID`
   - `S3_SECRET_ACCESS_KEY`
   - `YOUTUBE_API_KEY`
   - `RESEND_API_KEY`
   - `RESEND_FROM_EMAIL`
3. Optional credential fields remain `YOUTUBE_OAUTH_CLIENT_ID`, `YOUTUBE_OAUTH_CLIENT_SECRET`, `YOUTUBE_OAUTH_REFRESH_TOKEN`, `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `INSTAGRAM_ACCESS_TOKEN`, and `INSTAGRAM_USER_ID`.
4. Open `/api/health`. `ALPHA_BASE_URL` falls back to Render's `RENDER_EXTERNAL_URL`, so review emails target the deployed dashboard.

### 3. Configure unattended worker invocations

In the GitHub repository, add Actions secrets with the same names/values for `DATABASE_URL`, all five `S3_*` values, `YOUTUBE_API_KEY`, `RESEND_API_KEY`, and `RESEND_FROM_EMAIL`. Add `ALPHA_BASE_URL` with the full Render URL. Add the optional platform credentials if available. Enable Actions, open **ALPHA scheduled worker**, and run it once with **Run workflow**; that invocation attempts every remaining stage, and the hourly schedule remains as automatic recovery without the browser or laptop. The workflow validates the required secrets before installing dependencies and fails explicitly instead of silently falling back to an empty local SQLite database.

The workflow's hourly cadence is intentionally below GitHub Free's 2,000 private-repository minutes: one-minute billing would consume approximately 720 minutes in a 30-day month, leaving roughly 1,280 minutes for setup and active renders. Standard runners are free for public repositories. If actual private-repository rendering exceeds the remaining allowance, reduce the cadence, make the repository public if appropriate, or accept GitHub's metered Linux-runner overage; no application migration is required.

### Current £0 limits

- Neon Free: 0.5 GB database storage and 100 CU-hours per project/month.
- Cloudflare R2 Standard: 10 GB-month, 1 million Class A operations, 10 million Class B operations/month, and free egress.
- [Render Free](https://render.com/docs/free): 750 running instance-hours/workspace/month; sleeps after 15 minutes without inbound traffic and loses local files by design.
- [GitHub Actions](https://docs.github.com/en/billing/concepts/product-billing/github-actions): free standard runners for public repositories; 2,000 included minutes/month on GitHub Free private repositories. [Scheduled workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule) can be delayed and public-repository schedules disable after 60 days without repository activity.
- Resend: use its current free/low-cost allowance; the sending domain must be verified.

There is no unavoidable monthly component at this scale. Exceeding a provider allowance may suspend work or incur that provider's published usage charge, so inspect usage after the first real campaign.

## Optional creative enrichment

Campaign intake now preserves the raw brief and exposes fail-closed permissions for music, memes/reactions, B-roll, SFX and external images/video, including insert limits, volume range, ducking, required sources and prohibited types. Before submitting, users can upload authorised campaign music, reaction art and B-roll with licence and commercial-use attestations; production files are private S3 objects, while local development uses the filesystem adapter.

The worker persists an evidence-backed Enrichment Plan before FFmpeg rendering. Supported composition includes music loops/fades/speech ducking, timed SFX, image/video full-screen/PiP/overlays, and native punch-in, dynamic crop/speaker focus, freeze, emphasis text, keyword/progress/pull-quote treatment, blur, fast-cut and reaction-hold events. The review dashboard explains the timestamp, asset and reason for each event. Requests such as `remove music`, `less memes`, `more B-roll`, `change music`, `move meme to 4 seconds`, `regenerate enrichment`, and the combined acceptance edit create immutable child versions.

ALPHA ships no copied meme/music catalogue and requires no paid asset provider. Supply user-owned, public-domain or properly licensed assets; recorded metadata does not transfer or guarantee rights.

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

Local SQLite only: create a consistent backup with:

```powershell
.\.venv\Scripts\python.exe -m alpha.ops backup --destination backups\alpha.db
```

For production, use Neon's restore/history or `pg_dump`; `alpha.ops backup` refuses to treat a Postgres URL as a SQLite file. R2 objects are durable independently of app/worker restarts. Preserve the database and bucket as one logical backup set because database rows reference private `s3://` object URIs.

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
- `alpha/cloud.py`: stateless web entry point with optional local/opportunistic worker.
- `render.yaml`: diskless Render Free deployment Blueprint.
- `.github/workflows/alpha-worker.yml`: scheduled bounded worker invocations.
- `migrations/`: additive SQLite/Postgres schema.
- `web/`: responsive review dashboard.
- `tests/`: unit, API, durability, invariant, and end-to-end coverage.

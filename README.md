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

## Provider modes and external access

`ALPHA_PROVIDER_MODE=fixture` is the runnable CI/demo path. It does not download third-party media or imply live platform access. Set any other value to use the manual/import source fallback, which marks items as requiring authorised metadata/transcript import. Provider interfaces are in `alpha/providers.py` for source resolution/transcription, research, storage, email, rendering, and publication.

Live integrations are intentionally **not claimed complete**:

- YouTube metadata/playlist/transcript access needs an implementation using permitted YouTube APIs or user-authorised imports.
- Live social research needs platform-approved APIs and credentials; fixture/manual imports remain functional.
- Production email needs an SMTP/API adapter and credentials; V0 writes idempotent messages to `data/emails`.
- Direct posting needs each platform's approved posting API and OAuth credentials; V0 creates an approval-gated manual export instead.

No adapter may bypass access controls, CAPTCHA, or platform terms.

## Configuration

Copy `.env.example` values into the process environment. Important settings:

- `ALPHA_DATABASE_PATH`: SQLite database path.
- `ALPHA_STORAGE_PATH`: watermarks, rendered clips, and export packages.
- `ALPHA_EMAIL_SINK_PATH`: development email messages.
- `ALPHA_PROVIDER_MODE`: `fixture` or manual/import fallback.
- `ALPHA_API_TOKEN`: optional API token required through `X-Alpha-Token` when configured.
- `ALPHA_LEASE_SECONDS`: worker lease duration; expired leases are recoverable.

Secrets must be supplied through environment/deployment secret management and must never be committed or logged.

## Durable processing model

Each worker acquisition leases exactly one stage. The output and completed-stage checkpoint are committed before the next stage is queued. A killed worker's lease expires and another worker resumes the same stage; completed side effects are protected by stable uniqueness/idempotency keys. Logical jobs can therefore span many worker executions and do not assume one process lives for 72 hours.

## Approval and compliance invariants

- Only `SourceItem` records descended from the campaign's `ApprovedSource` set can become candidates.
- Deterministic and AI-evaluated QA are stored separately.
- A mandatory deterministic failure blocks approval and publication.
- Publication requires a persisted approval record and an idempotency key.
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
- `migrations/`: additive SQLite schema.
- `web/`: responsive review dashboard.
- `tests/`: unit, API, durability, invariant, and end-to-end coverage.


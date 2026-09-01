# AI Clipper — ALPHA V0

A research-led system for discovering, evaluating and producing short-form social media clips from approved source content.

AI Clipper is designed around **content reward campaigns**: a campaign can provide source videos, examples of successful clips, campaign requirements, branding and payout rules. The system researches the surrounding topic, analyses available source material, identifies promising timestamped moments, renders short-form clips and presents them for human review.

The project focuses not only on clip generation, but on building a **durable and auditable pipeline** that can process long-running campaigns without requiring a browser or a single worker process to remain online.

> **Status:** Advanced V0 prototype. The core processing pipeline, local/demo environment and most production adapters are implemented. Some external platform integrations still require credentialled live validation before the system should be considered production-complete.

## The Problem

Creating effective short-form clips from long-form content involves considerably more than cutting random sections from a video.

A useful system needs to answer questions such as:

* Which moments are actually worth clipping?
* What topics or formats are currently relevant?
* What made previous successful clips work?
* Does a candidate satisfy campaign requirements?
* Is the source material authorised and traceable?
* How should the clip be edited for short-form platforms?
* Did the final render actually meet the required technical rules?
* How can human feedback and real-world performance improve future decisions?

AI Clipper explores this as an **end-to-end research and media-processing problem**.

## How It Works

A campaign moves through a multi-stage processing pipeline:

```text
Campaign brief
      ↓
Source validation
      ↓
Source resolution & transcription
      ↓
Successful-example analysis
      ↓
Social / trend research
      ↓
Strategy generation
      ↓
Moment discovery
      ↓
Candidate ranking
      ↓
Creative enrichment planning
      ↓
FFmpeg rendering
      ↓
Deterministic & advisory QA
      ↓
Human review
      ↓
Approved export
      ↓
Performance feedback
```

Each processing stage is checkpointed so that interrupted jobs can resume rather than restarting from the beginning.

## Campaign Intake

Campaigns can contain:

* multiple approved source URLs
* examples of previously successful clips
* research topics and keywords
* campaign requirements
* branding and watermark configuration
* target social accounts
* creative permissions
* payout and qualified-view economics

The system validates and normalises these inputs before processing begins.

Source provenance is retained throughout the pipeline so that generated candidates can be traced back to approved campaign material.

## Source Resolution & Transcription

Source handling supports several workflows depending on available permissions and credentials.

For YouTube content, the live adapter can work with:

* YouTube Data API metadata
* playlists expanded into individual videos
* authorised caption tracks
* supplied timestamped transcripts
* rights-attested uploaded video/audio

Uploaded media can also be passed to a configurable **Whisper-compatible transcription command** to generate timestamped transcript segments.

A pre-processing readiness check verifies whether each source has the metadata, transcript and media required by later stages before expensive processing begins.

## Social Research

The research layer gathers evidence that can help inform clip selection.

Adapters exist for sources including:

* YouTube search and video statistics
* TikTok public metadata
* TikTok Research API where approved
* Instagram professional-account research where configured
* GDELT
* Google News RSS

Provider responses and failures are recorded separately so that the system can distinguish between:

* unavailable information
* provider limitations
* actual negative evidence

rather than silently treating missing data as meaningful data.

## Example & Style Analysis

Campaigns can include examples of clips that previously performed well.

These are used to derive signals about characteristics such as:

* pacing
* subject matter
* emotional tone
* humour
* surprise
* controversy
* usefulness
* quotability
* storytelling potential

The analysis layer is designed behind a provider abstraction.

The current local/free-capable implementation uses deterministic heuristics for several analysis tasks, while the architecture allows model-backed implementations to be introduced without coupling the core domain logic to a single AI provider.

## Candidate Discovery & Ranking

Timestamped source material is searched for potentially valuable moments.

Candidates can be evaluated using signals such as:

* relevance to campaign research
* similarity to successful examples
* emotional or narrative value
* humour
* surprise
* controversy
* usefulness
* quotability
* campaign requirements
* expected campaign economics

Scores are versioned and stored alongside their supporting evidence.

This allows ranking decisions to be inspected later rather than producing an unexplained "AI score".

## Video Rendering

Selected moments are rendered using **FFmpeg**.

The rendering pipeline supports:

* vertical **9:16** output
* H.264 video
* AAC audio
* captions
* watermarks
* dynamic crops
* punch-ins and zooms
* emphasis text
* freeze frames
* progress or keyword treatments
* authorised B-roll
* images
* sound effects
* music
* picture-in-picture overlays

Creative additions are first stored in an **Enrichment Plan**, preserving what was added, when it appears and why it was selected.

## Rights-Aware Creative Enrichment

Optional media can be discovered from approved or rights-compatible sources.

The project currently includes support for:

* cached authorised assets
* Openverse
* optional Pexels integration

Asset metadata can retain information such as:

* provider
* source URL
* licence
* attribution
* semantic tags
* stored object reference

If a suitable rights-safe asset cannot be found, enrichment is omitted rather than replaced with unverified media.

## Quality Assurance

Rendered clips pass through a rule engine before approval.

Deterministic checks can include:

* video duration
* aspect ratio
* resolution
* branding
* caption requirements
* source provenance
* campaign-specific mandatory rules

Deterministic failures are kept separate from advisory or AI-evaluated requirements.

A mandatory deterministic failure prevents publication.

This separation prevents an AI judgement from overriding a hard technical or compliance requirement.

## Human-in-the-Loop Review

AI Clipper does **not** automatically publish generated clips.

Once processing is complete, candidates are presented through a review interface where they can be:

* approved
* rejected
* changed

Edit requests can create new child versions while preserving the original render and review history.

Supported edit concepts include changes to:

* timing
* captions
* crops
* watermarks
* headlines
* B-roll
* music
* sound effects
* zooms and emphasis

Publication or export requires explicit approval.

## Durable Processing Architecture

Long-running media jobs should not depend on a single process surviving until completion.

AI Clipper therefore uses a **database-backed worker architecture**.

The worker system includes:

* persistent job queues
* stage checkpoints
* worker leases
* lease heartbeats
* retry tracking
* exponential backoff
* attempt history
* recovery of expired jobs
* idempotency keys

A worker can stop midway through a campaign and another worker can resume from the last persisted checkpoint.

This allows a large campaign to be processed across multiple independent worker executions.

## Persistence

The application supports two persistence configurations.

### Local Development

* SQLite
* local filesystem storage
* file-based email sink

### Production Architecture

* PostgreSQL
* S3-compatible object storage
* Resend email
* stateless application workers

The production deployment is designed so that important state does not depend on a particular application instance or local disk surviving.

## Deployment

The repository includes infrastructure for containerised and remote operation.

Supported tooling includes:

* Docker
* Docker Compose
* Render
* GitHub Actions
* PostgreSQL
* S3-compatible object storage

The remote architecture separates the web application from background processing.

Scheduled GitHub Actions workers can resume persisted campaigns and process the pipeline without requiring the user's computer or browser to remain active.

## Testing

The project includes automated coverage for areas including:

* API behaviour
* campaign intake
* source processing
* provider integrations
* worker durability
* retry and recovery behaviour
* authentication
* email
* rendering
* QA rules
* object persistence
* creative enrichment
* deployment contracts

The latest recorded full test run contains **52 passing tests**.

Development tooling also includes:

* `pytest`
* `ruff`
* CI verification
* JavaScript syntax checking
* FFmpeg render validation

## Technology Stack

### Backend

* **Python 3.11+**
* **FastAPI**
* **Uvicorn**
* **Pydantic**

### Data & Persistence

* **SQLite**
* **PostgreSQL**
* **psycopg**
* **S3-compatible object storage**
* **boto3**

### Media

* **FFmpeg / ffprobe**
* **Whisper-compatible transcription**

### External Research

* YouTube Data API
* TikTok oEmbed
* TikTok Research API
* Instagram Graph API
* GDELT
* Google News RSS
* Openverse
* Pexels

### Frontend

* HTML
* CSS
* JavaScript

### Infrastructure & Testing

* Docker
* Docker Compose
* GitHub Actions
* Render
* pytest
* Ruff

## Repository Structure

```text
AI-Clipper/
│
├── alpha/
│   ├── main.py             # FastAPI application
│   ├── pipeline.py         # Durable campaign pipeline
│   ├── services.py         # Application use cases
│   ├── domain.py           # Ranking, signals and QA logic
│   ├── providers.py        # Provider abstractions
│   ├── live_providers.py   # External research integrations
│   └── worker.py           # Background worker
│
├── migrations/             # SQLite/PostgreSQL migrations
├── tests/                  # Automated test suite
├── web/                    # Review dashboard
├── scripts/                # Development and operations scripts
├── .github/workflows/      # CI and remote worker automation
│
├── ARCHITECTURE.md
├── IMPLEMENTATION_STATUS.md
├── PRODUCT_BIBLE.md
├── TEST_PLAN.md
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

## Running Locally

Requires **Python 3.11+**.

On Windows:

```powershell
.\scripts\dev.ps1
```

The development script prepares the Python environment and starts the FastAPI application together with the local worker.

The application is then available at:

```text
http://127.0.0.1:8000
```

Production-style API and worker processes can also be run separately:

```bash
python -m uvicorn alpha.main:app --host 0.0.0.0 --port 8000
python -m alpha.worker
```

or using Docker:

```bash
docker compose up --build
```

## Current Development Status

Most of the V0 architecture is implemented, including:

* campaign intake
* durable workers
* strategy generation
* candidate ranking
* FFmpeg rendering
* QA
* review and editing
* approval-gated export
* feedback collection
* research-led experimentation
* deployment infrastructure

However, the project should still be considered **in development**.

A complete production campaign using all required live credentials and external services has not yet passed the final end-to-end acceptance criteria.

Some integrations therefore remain implemented but not fully validated against live credentialled environments.

For detailed status information, see:

* [`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md)
* [`ARCHITECTURE.md`](ARCHITECTURE.md)

## Design Principles

The project is built around several core principles:

* **Human approval before publication**
* **Evidence-backed recommendations**
* **Approved-source provenance**
* **Deterministic rules override advisory AI**
* **Recoverable long-running jobs**
* **Provider-independent architecture**
* **Idempotent external actions**
* **Rights-aware media handling**
* **Transparent failure states**
* **No dependence on a continuously connected browser**

These constraints turn AI Clipper from a simple video-cutting script into an exploration of how research, automation, media processing and human judgement can be combined into a reliable content-production system.

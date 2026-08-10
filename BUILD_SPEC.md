# ALPHA — Codex Build Specification

## Definition of done for V0

V0 is done only when a developer can run the application, submit a campaign containing multiple approved sources and successful examples, allow processing to continue without the browser, receive a review notification, inspect rendered candidate clips with explanations, request a change or reject with feedback, explicitly approve a clip, and complete the publication/export path while all key events are persisted.

External social/research APIs may be represented by compliant adapters and fixtures in CI where live credentials are unavailable. The architecture and contracts must be real; do not fake the core pipeline.

## Phase 0 — Repository bootstrap

Deliver:
- monorepo or clearly separated web/api/worker structure;
- README;
- environment example;
- AGENTS.md;
- migrations;
- test tooling;
- lint/format;
- Docker development option;
- seed/demo command.

Acceptance:
- one documented command launches dev stack;
- one documented command runs tests;
- clean installation from fresh checkout;
- health endpoint passes.

## Phase 1 — Campaign intake

Build:
- create/edit/view campaign;
- campaign economics;
- requirement builder;
- multiple approved source entries;
- YouTube video + playlist source types;
- successful-example URLs;
- research seeds;
- branding/watermark upload;
- platform/account selections;
- deterministic vs AI-evaluated requirement classification.

Acceptance:
- campaign persists;
- 25+ sources can be attached;
- 25+ successful examples can be attached;
- invalid/duplicate URLs handled cleanly;
- uploaded watermark stored via storage adapter;
- API validation tests.

## Phase 2 — Durable worker system

Build:
- PipelineJob table;
- queue;
- worker;
- leasing/heartbeat;
- checkpoints;
- retries;
- stage progress;
- recovery of expired leases.

Acceptance:
- submit campaign then close browser; job continues;
- kill worker mid-stage and restart; job resumes without restarting completed stages;
- duplicate worker does not duplicate completed side effects;
- simulated 72-hour logical job can progress across multiple worker restarts.

## Phase 3 — Source resolution and transcription

Build:
- source adapter interface;
- YouTube metadata/resolution adapter where permitted;
- playlist expansion;
- transcript pipeline;
- timestamped chunks;
- semantic index.

Acceptance:
- playlist resolves to concrete SourceItems;
- all items belong to campaign;
- transcript segments link to exact source/timestamps;
- semantic search returns source + timestamp;
- duplicate source resolution is idempotent.

## Phase 4 — Successful-example intelligence

Build:
- SuccessfulExample processing;
- extract/store metadata where available;
- transcript/text ingestion;
- structured analysis:
  hook, topic, subtopic, emotion, controversy, humour, context, structure, clip duration, headline, caption pattern, crop/framing, pacing where technically measurable;
- infer StyleProfile from multiple examples;
- provenance links.

Acceptance:
- campaign with fixtures produces a style profile;
- every inferred style field contains evidence/confidence;
- raw example evidence remains accessible.

## Phase 5 — Social research engine

Build provider interfaces first.

Capabilities:
- query generation;
- research targets;
- observation collection;
- metrics snapshots;
- creator baselines where available;
- outlier calculation;
- velocity calculation;
- topic/angle clustering;
- trend lifecycle;
- successful clipping-account analysis;
- saturation proxy;
- evidence storage.

Important:
- never bypass access controls or anti-bot measures;
- respect platform terms and permitted APIs/data access;
- support manual/import adapters if direct automated collection is unavailable.

Acceptance:
- fixture dataset with known outliers identifies expected outliers;
- repeated related posts form a cluster;
- raw observation and derived signals are separable;
- research report cites evidence IDs.

## Phase 6 — Strategy synthesis + source matching

Build:
- StrategyBrief object/view;
- trend ranking;
- style recommendations;
- semantic retrieval across ALL approved source items;
- separate "research-matched" and "independently interesting" candidate passes;
- duplicate/saturation checks;
- candidate score breakdown.

Candidate score initial components:
- research_alignment
- example_alignment
- hook_quality
- standalone_clarity
- humour
- controversy
- emotional_strength
- informational_value
- novelty
- exact_moment_saturation
- source_quality
- campaign_relevance
- rule_risk
- diversification

Weights configurable, versioned, and recorded with prediction.

Acceptance:
- candidate cites source and timestamp;
- candidate cites research/example evidence;
- ranking can explain why candidate A outranks B;
- candidate from any approved source can win;
- no unapproved source can become a render candidate.

## Phase 7 — Rendering + deterministic campaign rules

Build:
- RenderSpec schema;
- FFmpeg renderer;
- 9:16 conversion;
- subtitle/caption support;
- watermark overlay:
  file, position, opacity, padding, size;
- optional headline;
- cut/start/end controls;
- audio rules;
- reusable style-profile mapping.

Rule engine:
- duration;
- aspect ratio;
- resolution;
- watermark presence/position;
- captions required;
- prohibited/required metadata where machine-checkable;
- source provenance.

Acceptance:
- golden fixture renders deterministically;
- Whop-style watermark requirement can be configured through the campaign form with no campaign-specific hardcoded branch;
- missing mandatory watermark causes QA fail;
- changing watermark position requires no code change.

## Phase 8 — QA + review dashboard

Build:
- deterministic QA report;
- separate AI-evaluated QA;
- review page:
  video;
  source/timestamp;
  why selected;
  evidence;
  score breakdown;
  style used;
  campaign compliance;
  caption/post metadata;
  approve/change/reject.

Acceptance:
- deterministic mandatory failure prevents approval until corrected or campaign rule is edited with audit trail;
- user can reject with standard reason + free text;
- user can request natural-language edit;
- review history preserved.

## Phase 9 — Edit loop

Build:
- EditRequest;
- parse instructions to supported render changes;
- regenerate child ClipVariant;
- preserve parent;
- compare versions.

Initial supported instructions:
- start earlier/later;
- end earlier/later;
- captions larger/smaller;
- watermark larger/smaller;
- watermark position;
- crop adjustment;
- headline text/style token;
- remove/restore context segment where source allows.

Acceptance:
- "start 3 seconds earlier and make the watermark smaller" produces structured changes;
- new render is linked to previous version;
- rejected version never disappears.

## Phase 10 — Email notification

Build:
- Review-ready email;
- failed-needs-attention email;
- provider abstraction;
- development email sink.

Acceptance:
- exactly one review-ready notification per review bundle/idempotency key;
- email links to correct campaign review page;
- email does not contain secrets.

## Phase 11 — Approval-gated publication

Build:
- connected-account model;
- publishing adapter interface;
- explicit approval record;
- idempotency key;
- export/manual fallback;
- initial platform adapters only where officially supportable.

Acceptance:
- no publish method succeeds without approval record;
- retry does not double-post;
- unavailable API path creates export package/manual instructions instead of bypassing controls.

## Phase 12 — Feedback + performance

Build:
- post-review "How did Alpha do?" prompt;
- reason taxonomy;
- performance snapshots;
- manual performance entry fallback;
- Content Rewards outcome/revenue fields;
- account baseline;
- predicted vs actual.

Acceptance:
- user preference and market outcome stored independently;
- dashboard can show disagreements;
- revenue per clip and per human-time field supported.

## Phase 13 — Research Ledger + experiment framework

Build:
- StrategyPolicy versioning;
- ResearchLedgerEntry;
- Experiment;
- control/treatment assignment;
- exploration percentage config;
- outcome summariser;
- no automatic source-code rewriting.

Acceptance:
- each recommendation records policy version;
- an experiment can be created and evaluated;
- findings can update configurable weights only through auditable policy version;
- rollback to prior policy possible.

## Phase 14 — Operational hardening

Add:
- structured logging;
- error classification;
- retry policies;
- storage cleanup;
- basic rate limiting;
- auth/session security;
- secret hygiene;
- audit log;
- backup/restore notes;
- dependency licence review;
- CI.

Acceptance:
- critical flows integration-tested;
- no secrets in repository;
- fresh deployment documented;
- IMPLEMENTATION_STATUS.md accurate.

## Out of scope for V0

- fully autonomous publishing without approval;
- autonomous code rewriting/deployment;
- massive-scale scraping;
- bypassing platform controls;
- buying paid data feeds by default;
- perfect face tracking;
- complex custom ML training;
- multi-tenant billing SaaS;
- mobile native app.

## Engineering decision rules

1. Prefer the smallest robust implementation that preserves the architecture.
2. Do not remove product requirements to make the build easier.
3. Use interfaces for volatile external providers.
4. If live external access is unavailable, implement the adapter contract + fixtures + documented manual/import fallback.
5. Do not pretend an integration works if it has not been tested.
6. Keep the app usable at the end of every phase.

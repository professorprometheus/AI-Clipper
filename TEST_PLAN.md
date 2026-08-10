# ALPHA — V0 Test Plan

## Test layers

### Unit
- schemas/validation;
- scoring;
- rule evaluation;
- signal calculations;
- policy versioning;
- edit instruction parsing;
- idempotency helpers.

### Integration
- DB + API;
- queue + worker;
- storage adapter;
- transcript/index;
- renderer;
- QA;
- email sink;
- approval gate.

### End-to-end
Happy path:
campaign -> sources -> research fixtures -> candidates -> render -> QA -> email -> review -> approve -> publication fixture -> performance -> feedback.

Failure paths:
- worker killed and resumed;
- duplicated source;
- playlist partially resolves;
- transcription failure and retry;
- mandatory watermark missing;
- research provider unavailable;
- publishing provider unavailable;
- duplicate publish retry;
- expired approval/review action.

## Critical invariants

1. Unapproved source cannot be published.
2. Unapproved clip cannot be posted.
3. Mandatory deterministic requirement failure blocks approval/publication.
4. Job can recover from worker death.
5. Completed stages are not needlessly repeated.
6. Publish retries cannot duplicate posts.
7. Review/edit history is immutable/traceable.
8. AI confidence/soft checks cannot masquerade as deterministic pass.
9. Raw research evidence remains distinct from derived labels.
10. Every ranked candidate has source/timestamp provenance.

## Research fixtures

Create a deterministic fixture dataset containing:
- several creators;
- creator baselines;
- normal posts;
- at least 3 clear relative outliers;
- one emerging semantic cluster;
- one high-view non-outlier from a huge account;
- one saturated topic;
- successful example clips with a common style pattern.

Tests should demonstrate that Alpha prefers true relative outliers over misleading raw-view totals.

## Render fixtures

Include:
- sample landscape source;
- sample portrait source;
- sample SRT/VTT;
- sample watermark PNG;
- expected ffprobe properties.

Do not distribute copyrighted third-party source footage in the repository unless licensed/allowed. Use generated or permissively licensed fixtures.

## Durability test

Simulate a long logical job:
- complete stages 0–3;
- kill worker;
- expire lease;
- start replacement worker;
- resume at stage 4;
- inject transient failure;
- retry;
- reach awaiting_review;
- verify no duplicated side effects.

The test does not need to run for 72 wall-clock hours. It must prove the architecture does not depend on a 72-hour-lived process.

## Implemented automated coverage (2026-08-10)

- `tests/test_api_e2e.py`: full fixture path, real FFmpeg renders, research outlier discrimination, evidence and style output, pre-approval publish denial, natural-language child edit, approval, idempotent export, performance, feedback, one email and ledger policy provenance.
- `tests/test_api_e2e.py`: 25 approved sources + 25 examples and duplicate URL rejection.
- `tests/test_durability_and_rules.py`: four completed stages across short worker executions, abandoned lease aged by 73 hours, replacement worker, injected transient provider failure/retry, no duplicate completed stages/notification.
- `tests/test_durability_and_rules.py`: mandatory missing watermark fails QA and blocks approval/publication.
- `tests/test_durability_and_rules.py`: experiment evaluation, audited policy activation and rollback to the preserved prior policy.
- `tests/test_domain.py`: structured edit parsing/application and strict separation of AI-evaluated requirements from deterministic QA.

## Manual UI smoke (2026-08-10)

In the in-app browser against the real local dev server:

1. Opened the campaign dashboard and campaign intake form.
2. Submitted two approved sources (one playlist), three successful examples, seeds and configurable watermark requirements.
3. Left the page idle while the background worker progressed; reloaded to `awaiting_review` with three variants.
4. Inspected source/timestamp, selection explanation, evidence IDs, score breakdown and QA status.
5. Approved one variant and verified that manual export appeared only after approval.
6. Prepared the export and opened the populated Research Ledger.
7. Confirmed no browser console errors or warnings.

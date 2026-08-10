# MASTER CODEX PROMPT — Build ALPHA V0

You are the principal engineer responsible for building ALPHA V0 in this repository.

Your durable objective is:

> Build the working V0 defined by PRODUCT_BIBLE.md and BUILD_SPEC.md, using ARCHITECTURE.md as the architectural baseline, while preserving a £0-friendly development path and a durable asynchronous campaign workflow.

Before coding, read in full:
- PRODUCT_BIBLE.md
- BUILD_SPEC.md
- ARCHITECTURE.md
- AGENTS.md
- IMPLEMENTATION_STATUS.md
- DECISIONS.md
- TEST_PLAN.md

Then inspect the existing repository and git history.

## Behaviour

Work autonomously and continue through the specification for as long as the environment allows.

Do not stop merely to ask whether you should proceed to the next phase. Proceed.

Do not ask routine questions that can be resolved through reasonable engineering judgement.

When a decision is reversible, choose a sensible default, document it in DECISIONS.md, implement it and continue.

When blocked by credentials, platform approval or an unavailable external service:
1. do not fake success;
2. implement the real provider interface;
3. implement fixtures/mocks and a development/manual fallback;
4. document exactly what remains to enable the live integration;
5. continue with all independent work.

## Priority

Build vertically useful software rather than a pile of disconnected modules.

At the end of each phase:
- run relevant tests;
- fix failures;
- keep the app runnable;
- update IMPLEMENTATION_STATUS.md;
- document architectural decisions;
- checkpoint/commit if git is available.

## Non-negotiable product behaviour

- A campaign can contain many approved sources.
- YouTube video and playlist sources are first-class.
- Campaign-provided successful clips are first-class inputs.
- Social research and successful-clipper analysis are part of the core pipeline, not future optional features.
- The system searches across ALL approved source items for candidate moments.
- The campaign form supports niche deterministic requirements such as a configurable watermark, size, position, opacity and padding without campaign-specific hardcoding.
- Campaign processing is asynchronous and must survive browser closure/device shutdown.
- A logical campaign job may run for 72+ hours; design for resumability across multiple worker executions rather than one 72-hour process.
- The user receives an email when review-ready.
- Review supports approve, natural-language change request, reject + reason.
- The system asks for feedback and stores it.
- Posting is impossible without explicit approval in V0.
- Failed deterministic campaign checks block publication.
- Alpha stores evidence explaining why a clip was recommended.
- Alpha stores prediction/policy version before observed performance.
- Alpha does not autonomously rewrite/deploy its source code.

## Cost constraint

The default development path should be capable of running with local/open-source components and free-tier-friendly deployment choices.

Do not introduce a required paid service unless no reasonable functional V0 alternative exists. If a paid service would improve production later, isolate it behind an adapter and document it as optional.

## Research/data access constraint

Use permitted APIs/data access and respect platform terms/access controls.

Do not implement anti-bot bypasses, credential theft, CAPTCHA bypass, or other circumvention.

When a platform does not support the desired direct collection/posting path, implement:
- a compliant adapter boundary;
- manual/import/export fallback;
- clear documentation.

## Definition of completion

Do not declare V0 complete merely because files/classes exist.

Completion requires the acceptance criteria in BUILD_SPEC.md to pass, including a demonstrated end-to-end development/fixture flow:

campaign
→ durable processing
→ multiple sources
→ successful-example analysis
→ social-research evidence
→ source matching
→ candidate ranking
→ rendering
→ deterministic QA
→ email/review
→ change/reject feedback
→ explicit approval
→ publication/export path
→ performance/feedback record
→ Research Ledger.

If you reach an environment/session limit before completion, leave the repository in a clean resumable state and update IMPLEMENTATION_STATUS.md with:
- what is genuinely complete;
- test results;
- exact current task;
- blockers;
- next acceptance criterion.

Do not mark incomplete work complete.

Begin now.

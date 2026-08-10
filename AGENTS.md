# AGENTS.md — Instructions for Codex and other coding agents

You are building ALPHA.

Before changing code, read:
1. PRODUCT_BIBLE.md
2. BUILD_SPEC.md
3. ARCHITECTURE.md
4. IMPLEMENTATION_STATUS.md
5. DECISIONS.md

## Operating mode

- Work autonomously.
- Do not ask the user routine implementation questions.
- Make reversible, documented engineering decisions.
- Continue until all currently actionable acceptance criteria are satisfied.
- If a task is blocked by missing credentials/external access, implement and test the provider interface, fixture/mock path, and documented manual fallback; record the blocker; continue with independent work.
- Never claim a live integration is complete unless tested against that live integration.
- Commit/checkpoint coherent working increments if git access is available.
- Update IMPLEMENTATION_STATUS.md after every meaningful milestone.
- Update DECISIONS.md for non-trivial architectural decisions.
- Update TEST_PLAN.md when adding critical behaviour.

## Product constraints

- Research is core.
- Campaigns have many approved sources.
- Approved sources commonly include YouTube videos/playlists.
- Successful example clips are first-class inputs.
- The browser/device must not need to stay connected while processing.
- Durable campaign processing may logically take 72+ hours.
- Do not rely on one process staying alive for that entire duration.
- Posting requires explicit human approval in V0.
- Deterministic requirements are enforced by code.
- AI requirements remain separately labelled.
- Never publish from an unapproved source.
- Never bypass platform access controls.
- V0 should have a functional £0-friendly path.
- Avoid paid dependencies where a reasonable free/local path exists.
- Do not hardcode campaign-specific rules such as "if Whop". Use general configuration.

## Quality bar

For each phase:
- implement;
- test;
- run tests;
- fix failures;
- exercise the actual UI/API path where feasible;
- update docs/status.

Do not leave obvious TODO stubs in core paths and mark a phase complete.

## Safety against destructive work

- Do not delete user data/migrations/history to make tests pass.
- Prefer additive migrations.
- Preserve review/edit lineage.
- Preserve raw evidence and derived analysis separately.
- Never log secrets or OAuth tokens.

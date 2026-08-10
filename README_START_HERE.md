# ALPHA Codex Build Pack

## Start here

Create a new repository (or an empty project directory) and copy all files in this pack into its root.

Then open that repository in Codex and give Codex the contents of `MASTER_CODEX_PROMPT.md`.

Codex should treat the repository documents as durable project memory.

## Files

- `PRODUCT_BIBLE.md` — what Alpha is and what must remain true.
- `ARCHITECTURE.md` — system boundaries, domain model and durable pipeline.
- `BUILD_SPEC.md` — phased implementation + acceptance criteria.
- `AGENTS.md` — standing instructions for coding agents.
- `IMPLEMENTATION_STATUS.md` — resumable progress ledger.
- `DECISIONS.md` — architecture decision record.
- `TEST_PLAN.md` — critical tests and invariants.
- `MASTER_CODEX_PROMPT.md` — initial Codex instruction.

## When a Codex run ends before completion

Start another Codex run in the same repository and use:

> Continue building ALPHA. Read AGENTS.md and all project specification files, verify IMPLEMENTATION_STATUS.md against the code/tests, run the test suite, and continue from the first incomplete actionable acceptance criterion. Do not redo completed work unless evidence shows it is broken.

The repository, not a single chat session, is the durable memory.

## Important distinction

Codex itself does not need to remain one uninterrupted process for 72 hours.

The ALPHA application it builds MUST support campaign jobs whose logical processing can last 72+ hours by using durable checkpoints, retries and resumable workers.

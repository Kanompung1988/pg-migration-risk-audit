---
name: pg-migration-risk-audit
description: Identify review-worthy data-loss and lock-risk patterns in PostgreSQL SQL migration files before database release, including DROP TABLE, ALTER DROP COLUMN, unbounded UPDATE/DELETE, TRUNCATE, CREATE INDEX without CONCURRENTLY, and invalid concurrent-index transaction wrapping. Use during migration PR review and deployment planning; never executes SQL or connects to databases.
license: MIT
compatibility: Python 3.10+ standard library only; offline local SQL files; no database credentials or network.
metadata:
  author: AREAZERO Skill Lab
  version: "1.0.0"
---

# PostgreSQL migration risk audit

## Trigger / non-trigger
Use for human review of PostgreSQL `.sql` schema/data migrations, pre-deploy checks, and risk summaries in Claude Code or Codex. Do **not** use as SQL parser certification, a database execution tool, a general SQL dialect validator, or proof a migration is safe. Do not modify any SQL without developer approval.

## Procedure
1. Confirm the target files are PostgreSQL SQL migrations and inspect the repository's release environment; never paste production secrets.
2. Run `python scripts/audit.py /path/to/migrations --format markdown --fail-on high` from this skill directory. The scanner reads local files and **never connects or executes SQL**.
3. Triage **PG001–PG008** findings, with line numbers, severity, reasons and suggested review steps; see [rules](references/RULES.md).
4. Inspect potential exceptions manually (e.g. intentionally full-table updates, tiny tables, concurrent index outside transactions). Severity is an editorial gate, not an exploitation score.
5. Report affected files and exact command; avoid saying the database is safe just because no findings appeared. For CI use `--format json` and assert exit codes `0` (below threshold), `2` (findings at/above threshold), `1` (invalid/unreadable input).
6. Require a human DBA or owning developer to review lock duration, data recovery, table size and rollout plan before applying changes.

## Reproducible examples
- `python scripts/audit.py examples/unsafe.sql --format json --fail-on none` shows synthetic PG001/PG002/PG003/PG004/PG005/PG006/PG007/PG008 patterns without changing a database.
- `python scripts/audit.py examples/safe.sql --format markdown --fail-on high` produces zero findings on a narrowly scoped sample (not proof of safe production behavior).
- `python -m unittest discover -s tests -v` runs regression tests.

## Safety and boundaries
Static file-only scanner with SQL comment/string/dollar-quote masking; no SQL execution, network, credentials, or database privileges. Supports `.sql` inputs, file limit 512 KiB and directory limit 1,000 SQL files; rejects symlink inputs and malformed literals. Uses **heuristics**, not a complete PostgreSQL grammar: procedural SQL, CTEs, dynamic SQL, savepoints and advisory locks need human assessment. Index advice depends on PostgreSQL version and table size. Generated report contains rule IDs and file names, not SQL parameter values. Read [sources](references/SOURCES.md).

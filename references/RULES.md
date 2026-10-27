# PostgreSQL migration risk rules

| Rule | Level | Pattern | Review action |
|---|---|---|---|
| PG001 | Critical | `DROP TABLE` or `DROP SCHEMA` | Confirm backup, dependencies and approval |
| PG002 | High | `ALTER TABLE ... DROP COLUMN/CONSTRAINT` | Design expand/contract rollout |
| PG003 | Critical | `TRUNCATE` | Verify intent and recovery |
| PG004 | High | Direct `UPDATE`/`DELETE FROM` without lexical WHERE | Review intended row scope; CTEs/DO blocks not modeled |
| PG005 | Medium | `CREATE INDEX` without CONCURRENTLY | Evaluate write locks against table size and version |
| PG006 | High | `CREATE INDEX CONCURRENTLY` inside explicit BEGIN/COMMIT | Run outside transaction blocks |
| PG007 | Medium | `ALTER TABLE ... TYPE` | Evaluate table rewrite / lock impact |
| PG008 | High | `CASCADE` in DROP/ALTER | Audit dependent objects |

## Implementation and caveats

The scanner preserves newlines and semicolon boundaries while masking SQL string literals, identifiers, dollar-quoted bodies and nested comments. It cannot see dynamic SQL or unknown migration framework transaction behavior. `PG004` can be conservative about intentional bulk operations; `PG005` does not claim concurrent builds are always appropriate (Postgres documents additional resource usage and partition restrictions). No findings **does not imply migration safety**. Exit codes: `0` below threshold; `2` findings at or above threshold; `1` errors, including unsupported/unterminated quotes.

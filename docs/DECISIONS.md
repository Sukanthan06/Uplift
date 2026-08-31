# Decisions

Log of non-obvious technical choices made during the build. One entry per decision: what was chosen, why, and what alternative was rejected.

## Phase 1 — Schema: BIGSERIAL PKs, VARCHAR for taxonomy fields

**Chosen:** All five tables use auto-incrementing `BigInteger` primary keys. Taxonomy-driven columns (`method`, `psp`, `issuer`, `error_code`, `cause_family`, `chosen_action`, `outcome`, `status`) are `VARCHAR`, validated at the app layer (Pydantic), not Postgres `ENUM`.

**Why:**
- Sequential PKs give `audit_log` free insertion order — chain verification is `ORDER BY id`, no separate sequence column needed.
- The decline taxonomy (`taxonomy.py`) doesn't exist yet and is grounded in real PSP docs per CLAUDE.md — building it will add/adjust values repeatedly. Postgres `ENUM` would mean an `ALTER TYPE` migration every time; `VARCHAR` + Pydantic `Literal` validation avoids that churn during active iteration.

**Rejected:** UUID PKs (no natural ordering, adds complexity for no benefit in a single-writer batch/simulator system); Postgres native `ENUM` types (migration friction against the on-purpose reason ENUMs are meant to be strict).

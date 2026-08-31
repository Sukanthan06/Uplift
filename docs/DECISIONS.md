# Decisions

Log of non-obvious technical choices made during the build. One entry per decision: what was chosen, why, and what alternative was rejected.

## Phase 1 — Schema: BIGSERIAL PKs, VARCHAR for taxonomy fields

**Chosen:** All five tables use auto-incrementing `BigInteger` primary keys. Taxonomy-driven columns (`method`, `psp`, `issuer`, `error_code`, `cause_family`, `chosen_action`, `outcome`, `status`) are `VARCHAR`, validated at the app layer (Pydantic), not Postgres `ENUM`.

**Why:**
- Sequential PKs give `audit_log` free insertion order — chain verification is `ORDER BY id`, no separate sequence column needed.
- The decline taxonomy (`taxonomy.py`) doesn't exist yet and is grounded in real PSP docs per CLAUDE.md — building it will add/adjust values repeatedly. Postgres `ENUM` would mean an `ALTER TYPE` migration every time; `VARCHAR` + Pydantic `Literal` validation avoids that churn during active iteration.

**Rejected:** UUID PKs (no natural ordering, adds complexity for no benefit in a single-writer batch/simulator system); Postgres native `ENUM` types (migration friction against the on-purpose reason ENUMs are meant to be strict).

## Phase 3 — 5-arm historical treatment assignment (not binary)

**Chosen:** Extended `simulator/assignment.py` from a binary retry/no-retry coin flip to a uniform draw across 5 arms (`no_retry`, `retry_0h`, `retry_6h`, `retry_24h`, `retry_72h`), salted `v2` to mark the mechanism change explicitly.

**Why:** CLAUDE.md's own architecture wants `scorer.py` to return both `uplift(now)` and `uplift(best_time)`. With only a binary historical treatment, there is no logged experiment for what would have happened at +6h/+24h/+72h instead of now — training a "best time" estimate from that data would mean either faking it or quietly peeking at the hidden ground-truth curve, both of which violate non-negotiable #7 (honest evaluation). A genuine 5-arm experiment is the only way to learn timing causally without leakage.

**Rejected:** keeping binary assignment and falling back to a non-causal, cause-family-based heuristic for timing (same rule `rule_based` already uses). Simpler and avoids touching already-merged Phase 1 files a third time, but makes `scorer.py`'s "uplift(best_time)" dishonest — a heuristic dressed up as a model output.

## Phase 3 — Model grades the action it picked, never its own belief

**Chosen:** `score_uplift_policy` in `ml/evaluate.py` uses the trained model only to *choose* which attempts to retry and at what offset (ranking by predicted uplift). The *recovered value* of that choice is then computed from the hidden ground-truth probability at the chosen offset, never from the model's own predicted probability.

**Why:** Scoring a model's decisions using the model's own probability estimates would let a miscalibrated but confident model report an inflated result — the classic "grading your own homework" failure mode. Using ground truth to grade, and the model only to decide, is what makes the comparison against baselines (which are scored the same way) honest and apples-to-apples.

## Phase 3 — Honest result: uplift-ranked model ties, doesn't beat, rule-based

**Observed, not chosen:** on held-out test data (1,107 attempts, final 15 days), `uplift_ranked` recovers ₹599,005 at the same budget where `rule_based` recovers ₹602,287 — a ~0.5% loss, not a win.

**Why this is reported as-is:** CLAUDE.md non-negotiable #7 explicitly forbids tuning the simulator to make the model win. `uplift@20%` (0.76) and a positive, monotonically-rising Qini curve show the model's ranking is genuinely informative — the likely explanation is that `rule_based`'s hand-coded routing already captures most of what ~4,400 training examples can teach a model (skip hard declines, wait out outages, time insufficient-funds retries), and 1,107 test attempts is a small sample for stable causal-effect estimation. This is exactly the kind of result the project's evaluation methodology is designed to surface honestly rather than hide. See `docs/ASSUMPTIONS.md` (Uplift model).

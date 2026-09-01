# Uplift — Intelligent Payment Recovery

AI-driven payment recovery: diagnose failed payments with an LLM, score retry
uplift with a causal model, and let a deterministic policy engine decide
whether, when, and how to retry — optimizing for incremental revenue
recovered, not retry success rate.

Built for the Razorpay AI Buildathon, Track 03 (AI Revenue Recovery).

## Status

Phase 1 (Foundation) through Phase 7 (Dashboard) complete. Phase 8 (Ship — README/ARCHITECTURE polish, demo video) next.

### Phase 2 results (honest, no ML yet)

Baseline comparison from `python -m ml.evaluate`, on the 50k simulated attempts (6,693 failed):

| policy | recovered (INR) | retries | cost/INR recovered | customer contacts | double-charge near-misses |
|---|---|---|---|---|---|
| do_nothing | 369,031 | 0 | 0.0000 | 0 | 0 |
| retry_once | 2,797,993 | 6,693 | 0.0048 | 1,250 | 35 |
| retry_3x | 4,083,535 | 14,336 | 0.0070 | 2,643 | 35 |
| rule_based | 3,756,049 | 5,227 | 0.0028 | 1,250 | 35 |

The hand-picked rule-based policy (skip hard declines, time retries by cause) recovers 92% of retry-3x's revenue using 36% of the retries. Targeting and timing beat brute force even before any model exists — see `docs/DEMO_SCRIPT.md` and `docs/ASSUMPTIONS.md` for methodology.

### Phase 3 results (honest, this is the actual result — not a rehearsed win)

T-learner (2 XGBoost models) trained on a chronological split (4,438 train / 1,148 val / 1,107 held-out test). On the held-out test set, at the **same budget** as `rule_based` (863 retries, ₹1,726 cost):

| policy | recovered (INR) | retries | cost/INR recovered | customer contacts | double-charge near-misses |
|---|---|---|---|---|---|
| do_nothing | 60,272 | 0 | 0.0000 | 0 | 0 |
| retry_once | 448,728 | 1,107 | 0.0049 | 204 | 7 |
| retry_3x | 652,834 | 2,381 | 0.0073 | 431 | 7 |
| rule_based | 602,287 | 863 | 0.0029 | 204 | 7 |
| **uplift_ranked** | **599,005** | **863** | **0.0029** | 196 | 7 |

The learned model **ties, doesn't beat**, the hand-picked rule (−0.5%). `uplift@20% = 0.76` and a positive, monotonically-rising Qini curve show the model's ranking is genuinely informative — the likely explanation is that `rule_based`'s hand-coded routing already captures most of what ~4,400 training examples can teach a model, and 1,107 test attempts is a small sample for stable causal-effect estimation. Reported as-is per the project's non-negotiable: never tune the simulator to make the model win. See `docs/DECISIONS.md` and `docs/ASSUMPTIONS.md` ("Uplift model") for full methodology and honest discussion.

### Phase 4 results (honest — sweep confirms Phase 3's diagnosis)

`python -m ml.sensitivity_sweep` varies the four parameters CLAUDE.md names, in-memory on a smaller dataset (n=5,000/scenario) for turnaround speed. Plots saved to `backend/ml/output/sensitivity/` (gitignored).

- **Retry cost and customer patience show zero effect** on the recovered-revenue margin — mathematically expected (cost never enters the recovered-INR calculation; patience decay only bites multi-retry policies, and both `rule_based` and `uplift_ranked` issue a single retry per attempt). Reported as-is, not swapped for a metric that would show movement.
- **Outage frequency and base decline rate are the real story.** Across that grid, `uplift_ranked` never beats `rule_based` — but the gap shrinks sharply with more failure volume: −17% to −25% at half the default decline rate, narrowing to near-parity (−0.1% to −0.3% in several cells) near the default rate. This reframes Phase 3's result: the limiting factor looks like training data volume, not a structural flaw in the approach. Inference from the sweep, not verified at production scale.

See `docs/DECISIONS.md` (Phase 4 entries) and `docs/DEMO_SCRIPT.md` for full discussion.

### Phase 5 (reconciler, diagnoser, policy engine, action service)

Run live via `python -m app.demo_pipeline` (real Postgres, real Groq LLM calls). Four services, chained: `reconciler` (mocked gateway, resolves timeout ambiguity from the simulator's hidden ground truth) → `diagnoser` (Groq, structured `FailureDiagnosis`, Pydantic-validated, retries on invalid) → `scorer`/`scheduler` (Phase 3's trained model) → `policy_engine` (deterministic gate) → `action_service` (idempotent, bounded-retry gateway call).

**A live run caught a real bug the unit tests couldn't**: the LLM classified a `upi_invalid_account` decline (deterministically `card_or_account_issue`, a blocked hard decline) as `customer_error`. The first version of `policy_engine` trusted the LLM's own classification for its safety-critical block check and would have let that retry through. Fixed so the block check always uses the deterministic `taxonomy.py` classification, never the LLM's opinion — see `docs/DECISIONS.md`. This is the clearest evidence in the project that CLAUDE.md's "the LLM never makes money decisions" rule is load-bearing.

**Retry-exhausted incident, verified live**: a client forced to always return 503 produces exactly 3 total attempts (1 initial + 2 retries, exponential backoff), then `outcome=retry_exhausted` — no infinite loop, a bounded, visible incident.

**Stack deviation, logged not silent**: the diagnoser uses Groq (`openai/gpt-oss-120b`), not Anthropic — CLAUDE.md's stated stack, changed by explicit user direction this session. See `docs/DECISIONS.md`.

### Phase 6 (audit chain)

`app/services/audit.py`: hash-chained, tamper-*evident* — never "immutable," Postgres rows can always be edited; the chain makes edits detectable. `GET /audit/verify` walks the chain and reports which records are valid.

Verified live: ran the full Phase 5 pipeline (12 audit events), `verify()` reported all valid; directly tampered one row's `payload_json` via raw SQL (bypassing the app); `verify()` correctly reported that exact record invalid (`"payload does not match this record's stored hash"`) and every record after it invalid (`"chain already broken at an earlier record"`), while every record before it stayed valid — confirmed identically through both the Python function and the live `GET /audit/verify` HTTP endpoint. A more sophisticated tamper (recompute the edited row's own hash to hide it) is still caught, one record later, at the next row's now-mismatched `prev_hash` — covering a tamper completely requires re-deriving the whole chain forward from that point, not editing one row. See `docs/ASSUMPTIONS.md` ("Audit") and `docs/DECISIONS.md` for full methodology.

### Phase 7 (dashboard)

Single page, four tabs (tab-switched client-side, no router — "single page, no Next.js" per CLAUDE.md), Recharts for the Qini curve and sensitivity sweeps:

- **Overview** — simulator stats, Phase 2/3/4 result tables and charts, live pipeline activity. `GET /overview` combines a live DB query, `ml/evaluate.py`'s existing scoring functions, and Phase 4's pre-computed `results.json` (the sweep itself isn't re-run per request — it takes minutes).
- **Batch Run** — `GET /batch/run` streams N failed attempts through the real pipeline via Server-Sent Events; the page renders each result as it arrives.
- **Decision Detail** — per-payment diagnosis + uplift + decision + action + audit trail, joined from `GET /decisions/{id}`.
- **Audit Verify** — visualizes `GET /audit/verify`.

`app/services/pipeline.py` is a new, single reusable orchestration function (reconciler → diagnoser → scorer → policy_engine → action_service) used by both `demo_pipeline.py` and the Batch Run endpoint — replacing Phase 5/6's inline duplicate of the same logic, and fixing a real gap it had: `reconciliations` and `diagnoses` rows were never actually being persisted, only described in `audit_log` events. Two more real bugs were caught building this phase (Phase 3's dashboard table was silently missing the `uplift_ranked` row; a headless-Chromium `fullPage` screenshot quirk that looked like broken charts but wasn't) — see `docs/DECISIONS.md`.

Verified live in an actual browser (Playwright + Chromium, no console errors): all four tabs render with real data, Batch Run's SSE stream was driven end-to-end (Run batch → live rows appearing → completion), and the same LLM-vs-taxonomy disagreement from Phase 5 reproduced naturally in Decision Detail.

## Stack

- Backend: FastAPI + Python 3.11, PostgreSQL, SQLAlchemy 2.0
- ML: XGBoost (T-learner uplift model), Qini/uplift@k implemented manually (no causalml — unused, dropped)
- LLM: Groq (`openai/gpt-oss-120b`) for structured failure diagnosis — deviates from the originally planned Anthropic Claude, see `docs/DECISIONS.md` (Phase 5)
- Frontend: Vite + React + TypeScript + Tailwind + Recharts

See `ARCHITECTURE.md` for design details (added in Phase 8) and
`docs/DECISIONS.md` for rationale behind non-obvious technical choices.

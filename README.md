# Uplift — Intelligent Payment Recovery

AI-driven payment recovery: diagnose failed payments with an LLM, score retry
uplift with a causal model, and let a deterministic policy engine decide
whether, when, and how to retry — optimizing for incremental revenue
recovered, not retry success rate.

Built for the Razorpay AI Buildathon, Track 03 (AI Revenue Recovery).

## Status

Phase 1 (Foundation), Phase 2 (Evaluation harness), and Phase 3 (Uplift model) complete. Phase 4 (sensitivity sweep) next.

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

## Stack

- Backend: FastAPI + Python 3.11, PostgreSQL, SQLAlchemy 2.0
- ML: XGBoost + CausalML (T-learner uplift model)
- LLM: Claude (Anthropic) for structured failure diagnosis
- Frontend: Vite + React + TypeScript + Tailwind + Recharts

See `ARCHITECTURE.md` for design details (added in Phase 8) and
`docs/DECISIONS.md` for rationale behind non-obvious technical choices.

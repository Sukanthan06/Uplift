# Uplift — Intelligent Payment Recovery

AI-driven payment recovery: diagnose failed payments with an LLM, score retry
uplift with a causal model, and let a deterministic policy engine decide
whether, when, and how to retry — optimizing for incremental revenue
recovered, not retry success rate.

Built for the Razorpay AI Buildathon, Track 03 (AI Revenue Recovery).

## Status

Phase 1 (Foundation) and Phase 2 (Evaluation harness) complete. Phase 3 (uplift model) next.

### Phase 2 results (honest, no ML yet)

Baseline comparison from `python -m ml.evaluate`, on the 50k simulated attempts (6,693 failed):

| policy | recovered (INR) | retries | cost/INR recovered | customer contacts | double-charge near-misses |
|---|---|---|---|---|---|
| do_nothing | 369,031 | 0 | 0.0000 | 0 | 0 |
| retry_once | 2,797,993 | 6,693 | 0.0048 | 1,250 | 35 |
| retry_3x | 4,083,535 | 14,336 | 0.0070 | 2,643 | 35 |
| rule_based | 3,756,049 | 5,227 | 0.0028 | 1,250 | 35 |

The hand-picked rule-based policy (skip hard declines, time retries by cause) recovers 92% of retry-3x's revenue using 36% of the retries. Targeting and timing beat brute force even before any model exists — see `docs/DEMO_SCRIPT.md` and `docs/ASSUMPTIONS.md` for methodology.

## Stack

- Backend: FastAPI + Python 3.11, PostgreSQL, SQLAlchemy 2.0
- ML: XGBoost + CausalML (T-learner uplift model)
- LLM: Claude (Anthropic) for structured failure diagnosis
- Frontend: Vite + React + TypeScript + Tailwind + Recharts

See `ARCHITECTURE.md` for design details (added in Phase 8) and
`docs/DECISIONS.md` for rationale behind non-obvious technical choices.

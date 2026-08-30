# Karat — Intelligent Payment Recovery

AI-driven payment recovery: diagnose failed payments with an LLM, score retry
uplift with a causal model, and let a deterministic policy engine decide
whether, when, and how to retry — optimizing for incremental revenue
recovered, not retry success rate.

Built for the Razorpay AI Buildathon, Track 03 (AI Revenue Recovery).

## Status

Phase 1 (Foundation) in progress.

## Stack

- Backend: FastAPI + Python 3.11, PostgreSQL, SQLAlchemy 2.0
- ML: XGBoost + CausalML (T-learner uplift model)
- LLM: Claude (Anthropic) for structured failure diagnosis
- Frontend: Vite + React + TypeScript + Tailwind + Recharts

See `ARCHITECTURE.md` for design details (added in Phase 8) and
`docs/DECISIONS.md` for rationale behind non-obvious technical choices.

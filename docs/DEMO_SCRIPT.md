# Demo Script (5 minutes)

Updated at the end of every phase with what that phase adds to the video.

## Phase 1 — Foundation

Scene: `docker compose up` brings up Postgres, backend, frontend green. Cut to `alembic upgrade head` creating the five tables, then `python -m simulator.generator` running live: "50,000 payment attempts generated (6,693 failed) in ~6 seconds" — spot-check a few rows in the dashboard/psql showing realistic method mix (UPI-dominant) and decline codes grounded in Razorpay/ISO 8583/NPCI docs, not made up. Voiceover: every decline code is cited, every distribution parameter that isn't cited is explicitly marked illustrative in `sim_config.yaml` — nothing here pretends to be more real than it is.

## Phase 2 — Evaluation harness

Scene: run `python -m ml.evaluate`, comparison table prints live. Voiceover walks the table left to right: do-nothing recovers ~₹369k for free (customers self-resolve some failures on their own — that's the honest floor, not zero). Blind retry-once and retry-3x recover far more (₹2.8M, ₹4.1M) but retry-3x nearly doubles cost per rupee recovered over retry-once. Then the punchline: the hand-picked rule-based policy — which just knows *not* to retry hard declines and to time retries by cause (wait out outages, retry insufficient-funds near payday) — recovers 92% of retry-3x's revenue using 36% of the retries, at less than half the cost per rupee. This is the whole thesis, visible before any ML model exists: *targeting and timing beat brute force*. Phase 3's uplift model has to beat this rule-based bar, not just beat "retry everything."

Also surface: double-charge near-misses (35, only on baselines that actually retry) — a live example of why reconciliation-before-retry (Phase 5) isn't optional.

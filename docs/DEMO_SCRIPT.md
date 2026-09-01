# Demo Script (5 minutes)

Updated at the end of every phase with what that phase adds to the video.

## Phase 1 — Foundation

Scene: `docker compose up` brings up Postgres, backend, frontend green. Cut to `alembic upgrade head` creating the five tables, then `python -m simulator.generator` running live: "50,000 payment attempts generated (6,693 failed) in ~6 seconds" — spot-check a few rows in the dashboard/psql showing realistic method mix (UPI-dominant) and decline codes grounded in Razorpay/ISO 8583/NPCI docs, not made up. Voiceover: every decline code is cited, every distribution parameter that isn't cited is explicitly marked illustrative in `sim_config.yaml` — nothing here pretends to be more real than it is.

## Phase 2 — Evaluation harness

Scene: run `python -m ml.evaluate`, comparison table prints live. Voiceover walks the table left to right: do-nothing recovers ~₹369k for free (customers self-resolve some failures on their own — that's the honest floor, not zero). Blind retry-once and retry-3x recover far more (₹2.8M, ₹4.1M) but retry-3x nearly doubles cost per rupee recovered over retry-once. Then the punchline: the hand-picked rule-based policy — which just knows *not* to retry hard declines and to time retries by cause (wait out outages, retry insufficient-funds near payday) — recovers 92% of retry-3x's revenue using 36% of the retries, at less than half the cost per rupee. This is the whole thesis, visible before any ML model exists: *targeting and timing beat brute force*. Phase 3's uplift model has to beat this rule-based bar, not just beat "retry everything."

Also surface: double-charge near-misses (35, only on baselines that actually retry) — a live example of why reconciliation-before-retry (Phase 5) isn't optional.

## Phase 3 — Uplift model

Scene: run `python -m ml.train_uplift` live — two XGBoost models fit in seconds, chronological split printed (4,438 train / 1,148 val / 1,107 held-out test, never touched during training). Then `python -c "from ml.evaluate import run_phase3; run_phase3()"` prints the Qini curve and the head-to-head table.

Voiceover, honest version (this is the actual result, not a rehearsed win): at the same budget as the rule-based baseline, the learned model recovers ₹599,005 vs rule-based's ₹602,287 — essentially tied, a hair behind. Don't oversell it. Then pivot to what *does* show real signal: `uplift@20%` is 0.76 and the Qini curve rises steadily and stays positive across the whole ranking — the model has genuinely learned who's worth retrying, it just hasn't beaten a well-built hand-coded rule yet on this test slice. Say why, plainly: the rule already encodes the causal structure (skip hard declines, wait out outages, time insufficient-funds retries) that ~4,400 training examples can teach a model, and 1,107 held-out attempts is a small sample. This is the demo's credibility moment — CLAUDE.md's non-negotiable #7 says report wins and losses honestly, and this is the honest result.

Close the segment with the mechanism that's still real and demoable regardless of the head-to-head: `scorer.py` returns `uplift(now)` and `uplift(best_time)` for a single attempt, and `scheduler.py` turns that into an actual scheduled retry timestamp — show one example where the model picks "+24h" over "now" and explain why (issuer outage window, from the Phase 1 causal design).

## Phase 4 — Sensitivity sweep

Scene: run `python -m ml.sensitivity_sweep` live (~2-3 minutes, or cut to the finished output) — show the two saved plots, `sensitivity_sweeps.png` and `heatmap_outage_frequency_x_base_decline_rate.png`.

Voiceover, honest version again: two of the four swept parameters — retry cost and customer patience — show *zero* effect on the uplift-ranked-vs-rule-based margin, visible as flat lines. Explain why on camera, don't skip past it: retry cost only changes cost, never recovered revenue, so a revenue-based margin is mathematically guaranteed to be flat across it; patience decay only bites on multi-retry policies (`retry_3x`), and both `rule_based` and `uplift_ranked` only ever issue one retry per attempt. This is the sweep working correctly, not a wasted parameter.

The two that matter — outage frequency and base decline rate — tell the real story, best seen in the heatmap: the model never actually beats the rule-based baseline anywhere in the swept grid, but the gap shrinks sharply with more failure volume. At half the default decline rate (less training signal), it trails by 17-25%; near the default rate, several cells are within a percentage point of parity. Read this plainly on camera: the limiting factor looks like training data volume, not a structural flaw in the causal approach — a real deployment with production-scale transaction volume would be expected to close this further, though that's an inference from the sweep, not something verified at that scale. This is the same honesty standard as Phase 3, applied one level deeper.

## Phase 5 — Reconciler, diagnoser, policy engine, action service

Scene: run `python -m app.demo_pipeline` live, real Groq calls, real Postgres. Three real failed attempts flow through the full chain on camera: reconcile → diagnose → score → decide → act.

Walk the second example specifically — this is the best moment in the whole demo. The LLM classifies a `upi_invalid_account` decline as `customer_error`; the deterministic taxonomy says `card_or_account_issue`, a blocked hard decline. The policy engine correctly blocks the retry anyway (`rules_fired=['block_cause_families']`), because the block check never trusts the LLM's own classification — it uses the taxonomy lookup instead. Say plainly on camera: this disagreement happened for real, in this exact run, the first time this pipeline was tested live; the original version of the code *did* trust the LLM here and would have let the retry through. That's not a hypothetical edge case invented for the demo — it's why CLAUDE.md's "the LLM never makes money decisions" rule is load-bearing, not decorative.

Then the incident scene: inject a client that always returns 503. Show three total attempts (one initial, two retries, exponential backoff), then `outcome=retry_exhausted` and the escalation line. No infinite loop, no silent failure — a bounded, visible incident.

Close on the audit angle for Phase 6: every decision is now persisted, whether it led to a retry or not (`decisions` table has both `retry` and `no_retry` rows with `rules_fired` populated) — this is exactly the trail Phase 6's hash chain will wrap.

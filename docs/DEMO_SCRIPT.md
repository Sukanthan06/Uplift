# Demo Script (5 minutes)

Updated at the end of every phase with what that phase adds to the video.
The per-phase sections below are the full reference — everything that could
be said. **For the actual recording, follow the timed cut immediately
below** — narrating every phase section in full runs well past 5 minutes.

## The 5-minute cut (shooting order)

**0:00–0:20 — Hook.** One sentence, on camera or as a title card: "Don't
optimize for retry success probability — optimize for the incremental
revenue a retry creates." `docker compose up`, three services green.

**0:20–1:00 — Grounded simulation, honest baseline.** `python -m
simulator.generator` live (50k attempts, ~6s) — decline codes are cited
(Razorpay/ISO 8583/NPCI docs), not invented. Cut straight to `python -m
ml.evaluate`'s table: rule-based recovers 92% of retry-3x's revenue at 36%
of the retries. Say the thesis is already visible before any ML exists.

**1:00–2:00 — The uplift model, honestly.** `python -m ml.train_uplift`,
then the Phase 3 head-to-head table. Say the real number on camera: the
model ties the hand-picked rule, doesn't beat it (−1.6%). Pivot immediately
to `uplift@20%=0.78` and the rising Qini curve — the ranking is real signal,
just not enough yet to beat a good heuristic. This is the credibility beat;
don't rush past it or soften it.

**2:00–2:30 — Sensitivity sweep, one chart.** Cut to the heatmap image only
(skip the four flat-line sweeps in the video, mention them in one sentence).
Say: the model's gap narrows from −25% to near-parity as failure volume
rises — looks like a data problem, not a structural one.

**2:30–3:30 — Live pipeline, the best moment.** `python -m app.demo_pipeline`
live, real Groq calls. Land on the `upi_invalid_account` example: LLM says
`customer_error`, taxonomy says `card_or_account_issue`, policy engine
blocks the retry anyway. Say plainly: this disagreement happened for real,
on the first live run, and the original code would have let it through.
Then the 503 incident: 3 attempts, `retry_exhausted`, no infinite loop.

**3:30–4:10 — Audit chain.** Same run's tamper-and-verify: valid chain,
tamper one row via raw SQL, verify again — exact record flagged, everything
after it cascades, everything before stays valid. One line: "never
immutable, always tamper-evident."

**4:10–5:00 — Dashboard fly-through and close.** `localhost:5173`, all four
tabs in ~10 seconds each: Overview (the tables and charts just shown, now
live), Batch Run (start one, watch it stream), Decision Detail (the same
`upi_invalid_account` moment, now in the UI), Audit Verify (green dots).
Close on the one-sentence thesis again.

---

## Full reference, phase by phase

## Phase 1 — Foundation

Scene: `docker compose up` brings up Postgres, backend, frontend green. Cut to `alembic upgrade head` creating the five tables, then `python -m simulator.generator` running live: "50,000 payment attempts generated (6,693 failed) in ~6 seconds" — spot-check a few rows in the dashboard/psql showing realistic method mix (UPI-dominant) and decline codes grounded in Razorpay/ISO 8583/NPCI docs, not made up. Voiceover: every decline code is cited, every distribution parameter that isn't cited is explicitly marked illustrative in `sim_config.yaml` — nothing here pretends to be more real than it is.

## Phase 2 — Evaluation harness

Scene: run `python -m ml.evaluate`, comparison table prints live. Voiceover walks the table left to right: do-nothing recovers ~₹369k for free (customers self-resolve some failures on their own — that's the honest floor, not zero). Blind retry-once and retry-3x recover far more (₹2.8M, ₹4.1M) but retry-3x nearly doubles cost per rupee recovered over retry-once. Then the punchline: the hand-picked rule-based policy — which just knows *not* to retry hard declines and to time retries by cause (wait out outages, retry insufficient-funds near payday) — recovers 92% of retry-3x's revenue using 36% of the retries, at less than half the cost per rupee. This is the whole thesis, visible before any ML model exists: *targeting and timing beat brute force*. Phase 3's uplift model has to beat this rule-based bar, not just beat "retry everything."

Also surface: double-charge near-misses (35, only on baselines that actually retry) — a live example of why reconciliation-before-retry (Phase 5) isn't optional.

## Phase 3 — Uplift model

Scene: run `python -m ml.train_uplift` live — two XGBoost models fit in seconds, chronological split printed (4,438 train / 1,148 val / 1,107 held-out test, never touched during training). Then `python -c "from ml.evaluate import run_phase3; run_phase3()"` prints the Qini curve and the head-to-head table.

Voiceover, honest version (this is the actual result, not a rehearsed win): at the same budget as the rule-based baseline, the learned model recovers ₹592,384 vs rule-based's ₹602,287 — essentially tied, a hair behind. Don't oversell it. Then pivot to what *does* show real signal: `uplift@20%` is 0.78 and the Qini curve rises steadily and stays positive across the whole ranking — the model has genuinely learned who's worth retrying, it just hasn't beaten a well-built hand-coded rule yet on this test slice. Say why, plainly: the rule already encodes the causal structure (skip hard declines, wait out outages, time insufficient-funds retries) that ~4,400 training examples can teach a model, and 1,107 held-out attempts is a small sample. This is the demo's credibility moment — CLAUDE.md's non-negotiable #7 says report wins and losses honestly, and this is the honest result.

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

## Phase 6 — Audit chain

Scene: continue the same `python -m app.demo_pipeline` run straight into its final section. `verify()` runs first on the untouched chain — 12 records, `all_valid=True`. Say the sentence CLAUDE.md is explicit about on camera: never call this "immutable," Postgres rows can always be edited — what it actually provides is tamper-*evidence*.

Then the tamper: a direct SQL `UPDATE` on one `audit_log` row's `payload_json`, bypassing the app entirely — the kind of thing a rogue insider or a compromised DB credential could do. Run `verify()` again on camera: `all_valid=False`, `first_invalid_id` points at exactly the tampered row, and every record after it also flips to invalid with `"chain already broken at an earlier record"` — while everything before it stays valid. Hit `GET /audit/verify` in the browser or via curl to show the same result over HTTP, not just in a script.

If there's time, explain the harder case without demoing it live: a tamperer who also recomputes that one row's own hash to hide the edit doesn't get away with it either — the *next* row's `prev_hash` was fixed at write time to the original hash, so the break just moves one record later. Covering a tamper completely means re-deriving the whole chain from that point forward, not editing one row. This is in `test_audit.py` as `test_sophisticated_tamper_that_recomputes_its_own_hash_breaks_the_next_record` if it's worth cutting to the test output instead.

## Phase 7 — Dashboard

Scene: open the running frontend (`localhost:5173`), single page, a sidebar with four destinations — Overview, Batch Run, Decision Detail, Audit Verify. No page reloads switching between them; this is CLAUDE.md's "single page, no Next.js" literally.

**Overview**: scroll through live. Simulator stats, then the Phase 2 baseline table, then Phase 3's table *with the uplift-ranked row* and its Qini curve, then Phase 4's four sensitivity sweeps and the outage-frequency × decline-rate heatmap — every number on this page is either a live DB query or a pre-computed artifact from the phases already demoed, nothing re-derived or faked for the dashboard.

**Batch Run**: set attempts to 3-5, hit "Run batch," and let it stream live — real Postgres writes, real Groq calls, one row appearing per attempt as it completes. This is the best chance to land the block_cause_families moment live on camera again: if a `upi_invalid_account`-style attempt comes up in the batch, the Decision column will show `no_retry (block_cause_families)` even though the diagnosis panel says the LLM called it `customer_error` — say the same line as the Phase 5 scene, because it's the same real mechanism.

**Decision Detail**: click into the same attempt from the batch that just ran. Show the full trail — reconciliation, diagnosis (with the LLM's actual root-cause text), the decision and its rules_fired, the action outcome if any, and the hash-chained audit trail at the bottom, all for one payment, all real.

**Audit Verify**: hit "Re-verify," green dots down the list. If Phase 6's tamper demo was run earlier in the same session, this is where a red entry and everything after it would show up instead — the same `GET /audit/verify` call, now visualized.

One thing to flag if recording a `fullPage` screenshot for anything outside the live demo: headless Chromium's full-page capture can silently drop Recharts lines on a tall page even though they render correctly on screen — a browser/tooling quirk, not an app bug (see `docs/DECISIONS.md`). Screen-record or screenshot the visible viewport, not a stitched full-page capture, if this comes up.

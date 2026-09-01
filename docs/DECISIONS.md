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

## Phase 4 — Sensitivity sweep runs in-memory on a smaller dataset

**Chosen:** `ml/sensitivity_sweep.py` runs generate → train → evaluate entirely in-memory (never touching Postgres or the production `ml/output/*.pkl` files) with `n_attempts=5000` per scenario, versus the production 50,000.

**Why:** CLAUDE.md names four parameters to sweep; a full one-at-a-time sweep across sensible ranges is ~26 scenarios, plus a 5x5 grid for the heatmap (25 more) — 51 full pipeline runs. At 50k attempts per run this would take a long time and would repeatedly overwrite the trained models Phase 3's headline numbers depend on. 5,000 attempts per scenario is still enough failed attempts (roughly 650-700) to train and evaluate a real T-learner, and the in-memory path (bypassing the DB entirely) makes each scenario fast enough to run the whole sweep in a few minutes.

**Rejected:** sweeping at full 50k scale (too slow for the timeline, and risks a scenario run silently leaving stale models in `ml/output/`); testing only the two parameters that turned out interesting (would undercut the "vary the four named parameters honestly" instruction — the flat results for `retry_cost` and `patience_decay` are reported too, not hidden, because they're real and explainable, not because the sweep failed).

## Phase 4 — Honest result: `retry_cost` and `patience_decay` show zero sensitivity on the recovered-INR margin

**Observed, not chosen:** sweeping `retry_cost_inr` from ₹0.5 to ₹20, and `patience_decay.per_attempt_multiplier` from 0.5 to 1.0, produces an *identical* `uplift_ranked` vs `rule_based` margin at every value (flat lines in `ml/output/sensitivity/sensitivity_sweeps.png`).

**Why this is real, not a bug:** the margin metric is defined on `recovered_inr`, and `retry_cost_inr` only ever multiplies `total_retries` into `cost_inr` — it never appears in the recovered-value calculation, so a revenue-based margin is mathematically guaranteed to be flat across it. `patience_decay` compounds across *successive* retries in a plan (`p * decay**i`), but `rule_based` and `uplift_ranked` both only ever issue a single retry per attempt (`i=0`, `decay**0=1`) — only `retry_3x`'s multi-offset plan is sensitive to it, visible as the one sloped line in the bottom-right sweep plot. Reported as-is rather than swapped for a metric that would show movement, per the same honesty standard as the rest of the project.

**Consequence for the heatmap:** paired `outage_frequency` with `base_decline_rate` instead of `retry_cost` (the originally planned pairing, before this was understood) — a `retry_cost` axis would have produced 6 identical columns, wasting half the plot.

## Phase 4 — Honest result: the model never wins in the swept space, but the gap is mostly a data problem

**Observed, not chosen:** across the `outage_frequency` x `base_decline_rate` grid, `uplift_ranked` never beats `rule_based` (no green cells). But the gap shrinks sharply with more failure volume: at 0.5x the default decline rate (fewer failed attempts, less training signal), the model trails by −17% to −25% across every outage frequency; by 1.0-1.5x decline rate, the gap narrows to near-parity (−0.1% to −0.3% in several cells).

**Why this matters:** it reframes Phase 3's "ties, doesn't beat" result — the limiting factor looks like training/test sample size (failure volume), not a structural flaw in the T-learner approach. A production deployment with real transaction volume (far more than this simulator's 90-day, 50k-attempt window) would be expected to close this gap further. This is an inference from the sweep, not a claim verified at production scale — flagged as such rather than overstated.

## Phase 5 — LLM provider switched from Anthropic to Groq

**Chosen:** `app/services/diagnoser.py` uses the `groq` SDK (model `openai/gpt-oss-120b`), not `anthropic`. `.env`'s `ANTHROPIC_API_KEY` placeholder was replaced with `GROQ_API_KEY`/`GROQ_MODEL`.

**Why:** explicit user direction this session, not my own call — CLAUDE.md's Stack section says Anthropic and "do not deviate without asking"; the user is the one asking, which satisfies that rule rather than breaking it. Logged here so the deviation is visible, not silent. No real Anthropic key was ever configured in this environment (still the `sk-ant-xxxx` placeholder when checked); a real Groq key was supplied and used for live verification of every example in this phase's demo run.

## Phase 5 — policy_engine's block check uses the deterministic taxonomy, never the LLM's own classification

**Chosen:** `policy_engine.decide()` takes `cause_family` as a separate parameter (the deterministic `taxonomy.py` lookup for the attempt's `error_code`) and checks `block_cause_families` against that — never against `diagnosis.cause_family`, the LLM's own output.

**Why:** caught live, not in review. Running `app/demo_pipeline.py` against the real Groq API, the model classified a real `upi_invalid_account` attempt (taxonomy: `card_or_account_issue`, a blocked hard decline) as `customer_error` instead — and the first version of `policy_engine.py` trusted that classification, letting a retry through that should have been blocked. CLAUDE.md non-negotiable #1 says the LLM never makes money decisions; a policy gate that blocks or allows a retry based on the LLM's own classification is exactly that, one level removed. Fixed by decoupling the safety-critical block check from the LLM entirely — `diagnosis` is still used for its `confidence` gate and its human-readable `root_cause`, just not for the blocking decision. `require_diagnosis_confidence`'s rationale was updated to match (it no longer exists "to trust the classification for the block check," since that check no longer uses the classification at all).

**Consequence:** this is exactly the kind of thing non-negotiable #7 (honest evaluation, verify rather than assume) argues for building a live smoke test, not just unit tests with fake clients, before calling a phase done — the bug was invisible to `test_policy_engine.py`'s hand-picked fixtures because they never exercised a real LLM's actual (occasionally wrong) judgment.

## Phase 5 — every policy decision is persisted, not just approved retries

**Chosen:** `demo_pipeline.py` writes a `decisions` row for every attempt that reaches `policy_engine.decide()`, regardless of `chosen_action`. `action_service.execute_retry()` is only called when `chosen_action == "retry"`.

**Why:** the first version only persisted a decision when it led to a retry, so a blocked decision (e.g. the `block_cause_families` case above) left no row in the `decisions` table at all -- just a print statement. That's a real gap against the schema's evident intent (an audit trail of every decision made and why) and against Phase 7's dashboard needs (CLAUDE.md: "Decision Detail" shows diagnosis + uplift + decision + action, which requires blocked decisions to be visible too, not only approved ones).

## Phase 5 — `xgboost-cpu` instead of `xgboost`

**Chosen:** `pyproject.toml` depends on `xgboost-cpu`, not `xgboost`. Same Python API (`import xgboost as xgb` unchanged), drop-in compatible, all 70 tests pass identically after the swap.

**Why:** rebuilding the Docker backend image after adding `groq`/`matplotlib` this phase revealed that `xgboost`'s Linux wheel unconditionally depends on `nvidia-nccl-cu12` -- a 342MB CUDA library -- for Python <3.12 on Linux, regardless of whether GPU training is ever used. This project trains on CPU only, everywhere. The dependency was invisible locally because it's a Linux-only wheel (the local Windows dev venv never resolves it), but it turned a ~3-minute Docker build into one that was still downloading after 10+ minutes. `xgboost-cpu` is PyPI's official CPU-only variant of the same package -- same API surface, no CUDA stack. Docker build time dropped back to ~3 minutes with the swap.

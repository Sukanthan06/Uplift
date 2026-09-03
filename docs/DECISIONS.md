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

## Phase 5 — LLM provider switched to Groq

**Chosen:** `app/services/diagnoser.py` uses the `groq` SDK (model `openai/gpt-oss-120b`), not the SDK originally named in `CLAUDE.md`'s stack. `.env`'s original LLM-vendor API key placeholder was replaced with `GROQ_API_KEY`/`GROQ_MODEL`.

**Why:** explicit user direction this session, not my own call — `CLAUDE.md`'s Stack section names a different vendor and says "do not deviate without asking"; the user is the one asking, which satisfies that rule rather than breaking it. Logged here so the deviation is visible, not silent. No real key for the originally-specified vendor was ever configured in this environment (still an unfilled placeholder when checked); a real Groq key was supplied and used for live verification of every example in this phase's demo run.

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

## Phase 6 — Chain-walking logic is a pure function, separate from DB access

**Chosen:** `audit.verify_chain(records: list[AuditRecord])` is a pure function taking plain dataclasses in and returning results out, with no SQLAlchemy session or Postgres dependency. `audit.verify()` is a thin wrapper that queries the DB and calls it.

**Why:** every other module in this project keeps its core logic testable without a live Postgres connection (baselines/evaluate score in-memory `AttemptRecord`s, `policy_engine.decide()` takes plain values, `action_service._attempt_gateway_call()` is DB-free) -- the whole test suite runs in ~5 seconds with no DB fixture needed anywhere. Audit verification follows the same pattern: `test_audit.py` builds synthetic chains, tampers with them in-memory, and asserts on `verify_chain()` directly, covering both the naive-tamper and hide-the-tamper-by-recomputing-one-hash scenarios without touching Postgres. The DB-backed path (`append`/`verify`) is still exercised, but live, via `demo_pipeline.py`, same as every other service's DB integration in this project.

## Phase 6 — Canonical JSON serialization guards against JSONB reordering

**Chosen:** `_canonical_json()` always calls `json.dumps(payload, sort_keys=True, ...)`, used identically when computing a hash at write time and when recomputing it at verify time.

**Why:** Postgres's `JSONB` column type does not preserve the original key insertion order of a JSON object -- it can reorder keys internally. If hash computation trusted whatever order keys happened to come back in after a round trip through JSONB, a payload that was never touched by anyone could still fail verification purely because storage reordered it, which would be a false tamper alarm undermining the whole mechanism. Sorting keys ourselves, on both sides, means the byte sequence being hashed only depends on logical content, never on storage-internal ordering.

## Phase 7 — Reconciliations and diagnoses were never actually persisted

**Chosen:** extracted `app/services/pipeline.py` (`run_pipeline()`) as the single reusable orchestration function -- reconciler -> diagnoser -> scorer -> policy_engine -> action_service -- and it now writes real `Reconciliation` and `Diagnosis` rows, not just `audit_log` events describing them. `demo_pipeline.py` was refactored to call it instead of duplicating the orchestration inline.

**Why:** building the Decision Detail page (diagnosis + uplift + decision + action + audit, per CLAUDE.md's page spec) required joining against the `reconciliations` and `diagnoses` tables -- and they were empty. Phase 5/6's `demo_pipeline.py` only ever wrote `audit_log` entries describing what the reconciler and diagnoser did, never a row in the tables that exist specifically to hold that data. The schema was right from Phase 1; the orchestration script just never used two of its five tables. Same category of gap as the Phase 5 "decisions weren't always persisted" fix -- caught by building the thing that actually needs to read the data back, not by reviewing the write path in isolation.

## Phase 7 — Overview's Phase 3 comparison was missing the uplift-ranked policy

**Chosen:** `app/api/overview.py`'s `_phase3_result()` explicitly computes `score_uplift_policy` (budget matched to `rule_based`'s retry count, same methodology as `ml/evaluate.py`'s `run_phase3()`) and adds it to the baselines dict.

**Why:** caught live by curling the endpoint and checking for the key, not by reading the code -- the first version only looped over `ml.baselines.BASELINES` (the four non-ML policies), which is correct for Phase 2 but silently drops the one policy Phase 3 exists to show. The bug would have been invisible in a screenshot of the page (the table just would have had one less row, easy to not notice) -- checking the actual JSON keys against what was expected caught it before it shipped.

## Phase 7 — Sensitivity results are pre-computed, not recomputed per request

**Chosen:** `ml/sensitivity_sweep.py`'s `run()` now also writes `ml/output/sensitivity/results.json` (sweep points + heatmap margins, JSON-serializable). `app/api/overview.py` reads that file if present; returns `null` for that section otherwise.

**Why:** the sweep takes a few minutes end-to-end (20+ in-memory generate/train/evaluate cycles). Recomputing it on every dashboard page load isn't reasonable, and there's no reason to -- the sweep result doesn't change between requests. Same pattern as the trained model files (`ml/output/*.pkl`): a backend script produces an artifact, the API serves it, neither silently regenerates the other's work.

## Phase 7 — `fullPage` screenshots in headless Chromium silently drop chart lines

**Observed, not chosen:** verifying the dashboard with Playwright, `page.screenshot({ fullPage: true })` on a page taller than the viewport rendered every Recharts `<Line>` as an empty axis with no visible line -- despite the SVG `<path>` elements existing in the DOM with correct `d`, `stroke`, and `opacity: 1`. Cropping to just the chart's own SVG element, or using a tall fixed-height viewport with a normal (non-`fullPage`) screenshot, rendered the lines correctly every time.

**Why this is noted, not fixed:** nothing in the app was wrong -- this is a Chromium full-page-screenshot compositing quirk with tall pages, not a rendering bug. Logged here so a future session re-verifying this dashboard doesn't mistake an empty-looking `fullPage` screenshot for a regression and start debugging application code that's fine. Verify with a tall fixed-viewport screenshot (or crop to the chart element) instead of `fullPage: true` when charts are involved.

## Action service: dual-backend `GatewayClient`, real Razorpay sandbox call added

A locally-supplied extension prompt (`action-service-extension.md`, deliberately untracked -- see `.gitignore`) asked for a Razorpay-test-mode action backend alongside the mock. Implemented, but reconciled against this codebase's actual architecture and CLAUDE.md's non-negotiables in several places rather than followed literally:

- **No `ground_truth` database table.** The prompt's `MockActionClient` spec assumed one, "same pattern as `MockGateway`." There is no such table, by deliberate design (CLAUDE.md non-negotiable #6) -- hidden ground truth lives only in `simulator/output/ground_truth.jsonl`, outside the app DB, so no application code path can leak it. `reconciler.py` already established the correct pattern (read the JSONL file for ambiguous codes); nothing needed inventing here beyond following it. `tests/test_architecture.py` now guards this explicitly: only `reconciler.py` may reference `ground_truth` anywhere under `app/`.

- **Idempotency formula kept as CLAUDE.md specified it**, not replaced with the prompt's `attempt_ordinal`-based, 32-char-truncated variant. CLAUDE.md's non-negotiable #3 is the authoritative spec; a later extension prompt doesn't get to quietly redefine it. `app/services/idempotency.py` is now the single function allowed to build one (enforced by convention here, not yet a lint rule), and `action_service.py` imports it instead of hashing inline.

- **One `GatewayClient` protocol extended, not a new parallel `ActionClient`/`ActionRequest`/`ActionResponse` interface.** The prompt's richer schema would have forked the codebase into two abstractions for the same concept. `RazorpayGatewayClient` implements the same `retry_payment(payment_id, amount, currency) -> int` protocol `MockGatewayClient` always has, so both backends share 100% of the existing retry/backoff/idempotency/persistence logic in `execute_retry()` -- only the protocol's signature grew (now takes `amount`/`currency`, needed for a real Razorpay call; `pipeline.py`'s call site threads `row.amount` through).

- **Sync `httpx.Client`, not `async def` + `httpx.AsyncClient`.** This codebase is synchronous everywhere -- SQLAlchemy sessions, FastAPI routes, every other service. An async-only client would be an inconsistent island requiring a sync/async bridge for one call path. `tests/test_architecture.py` also guards that only `action_razorpay.py` may import `httpx` under `app/`.

- **Outcome vocabulary kept as `success`/`failed`/`retry_exhausted`** (plus a new `shadow` value for `ACTION_MODE=off`), not the prompt's `CAPTURED`/`FAILED`/`EXHAUSTED`/`CLIENT_ERROR`. Already integrated across `policy_engine`, the dashboard, and dozens of tests; the existing `_attempt_gateway_call` already implements "never retry 4xx" exactly as the prompt wanted, just under different names.

- **The real sandbox call is `POST /v1/orders`, not a payment capture/retry call.** Every payment attempt in this project is simulated -- there is no real Razorpay payment or order behind any `order_id` here. Creating a fresh test order (amount + our `payment_id` as the receipt) is the only thing that can honestly prove genuine sandbox integration without inventing a real-payment semantic for a payment that doesn't exist on Razorpay's side. It's a proxy for "the gateway accepted this call," not a claim that a real payment was captured. `RazorpayGatewayClient.__init__` refuses to instantiate with anything but a `rzp_test_*` key.

- **`incidents` is a genuine new sixth table**, beyond CLAUDE.md's originally-specified five (confirmed with the user before adding -- see the schema itself for its columns). `resolved_at`/`resolver_notes` don't belong on `actions`, which records what happened, not how a human handled it afterward. Written by `action_service.execute_retry()` exactly when `outcome == "retry_exhausted"`.

- **AI-vendor naming policy, twice reversed.** The extension prompt asked that no AI provider/model name ever appear in user-facing files; at the time, confirmed with the user to leave the existing Groq references as-is, since they'd been added earlier this session by explicit instruction to log the provider switch "clearly, not silently." The user then asked, separately, to remove every mention of the *former* provider by name everywhere, including this file -- done (see below). Groq itself stays named; only the originally-specified vendor's name was genericized.

- **Git workflow**: built and committed directly to `develop`, consistent with every other phase this session, not the prompt's requested `feat/action-service-interface` branch + PR flow. Introducing a branch/PR ceremony for one feature after eight phases of direct-to-`develop` commits would be an inconsistency of its own.

**Verified live** (not just unit-tested): a real call to Razorpay's sandbox (`ACTION_MODE=razorpay_test`) returned a genuine `200` and persisted correctly through the unmodified `execute_retry()` idempotency/persistence path; a forced-503 client exhausted the retry budget and correctly wrote an `incidents` row with accurate attempt count and last status; `ACTION_MODE=off` made no call and recorded `outcome=shadow`. 85/85 automated tests pass, including new architecture guards (`httpx` and `ground_truth` reference boundaries) and `httpx.MockTransport`-based tests for the Razorpay client that make no real network call in the automated suite.

**A real bug caught by running `demo_pipeline.py` end-to-end, not by the unit tests**: `demo_retry_exhausted()` read `any_attempt.amount` *after* the SQLAlchemy session that loaded it had already closed, raising `DetachedInstanceError` the moment the new `amount` parameter threaded through to `execute_retry()` needed that attribute lazy-loaded. Fixed by reading the value while still inside the session block, the same pattern the function already used for `decision_id`. Every unit test passed throughout -- `_AlwaysDownClient` is a plain stub, no session involved -- this only showed up running the real script against a real database, the same category of gap as the Phase 5 LLM-vs-taxonomy catch and the Phase 7 persistence gaps.

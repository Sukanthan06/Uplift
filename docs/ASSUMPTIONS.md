# Assumptions

Frozen assumptions behind the simulator, policy, and evaluation. Each assumption should cite a source where possible and be revisited only deliberately, not silently.

## Simulator

Frozen 2026-08-31, Phase 1. Implementation: `backend/simulator/{taxonomy,sim_config,assignment,generator}.py`.

### (a) Causal mechanism

Every failed root attempt (`attempt_no=1`) gets a hidden, per-attempt recovery-probability curve, determined by its `cause_family` (from the decline taxonomy — see below) and, for technical/bank-downtime failures, an issuer outage calendar:

- **`technical_bank_downtime`**: low probability of unprompted recovery (0.05). If retried while the issuer is still in a simulated outage window, low probability of success (0.05); if retried after the outage clears, high probability (0.85). This is the mechanism that makes retry *timing*, not just retry yes/no, matter — an issuer can be down at attempt time and back up 6–24h later.
- **`insufficient_funds`**: probability of success rises with retry delay (0h: 0.10 → 72h: 0.55), modeling a payday-shaped effect. Rewards "retry later" over "retry now."
- **`card_or_account_issue`** (hard declines — expired/blocked card, generic issuer decline): flat, low probability (~0.04) regardless of when or whether retried. This is the case the uplift model must learn to *not* retry.
- **`customer_error`** (wrong OTP/CVV, cancelled checkout): near-zero unprompted recovery (0.05), moderate probability if retried/prompted (0.35–0.45), since a retry here effectively means re-prompting the customer.
- **`risk_fraud`**: low probability (~0.06), roughly flat — retrying a risk-flagged transaction rarely helps and isn't modeled as improving with time.

Issuer outages are generated per issuer (7 major Indian banks, listed in `sim_config.yaml`) as a sequence of down/up windows across the 90-day simulation window: gap between outages ~ exponential (mean 14 days), outage duration ~ lognormal capped at 12h. While an issuer is down, the technical-failure share of that issuer's decline codes is upweighted (6x). **These specific numbers are illustrative design choices, not sourced statistics** — real-world outage frequency/duration and recovery-probability curves are proprietary to PSPs and issuers. They're isolated in `sim_config.yaml` specifically so Phase 4's sensitivity sweep can vary them and show where the policy's advantage holds up and where it doesn't.

`generator.py` samples **both** potential outcomes per failed attempt from this hidden curve — the observed outcome under whichever treatment was actually assigned (below), plus the full counterfactual curve — which is what makes honest offline Qini/uplift evaluation possible later (real production data never has both).

**Leakage boundary**: the hidden curve (`cause_family`, `p_recover_unretried`, `p_recover_offsets`) is written to `backend/simulator/output/ground_truth.jsonl`, a file entirely outside the application database/schema. No application code path (reconciler, policy_engine, scorer) can query it — this is a structural guard for CLAUDE.md's non-negotiable #6, not just a naming convention. Only `ml/train_uplift.py` and `ml/evaluate.py` (Phase 3) are meant to read it: the former to build labels, the latter to score honestly. `ml/features.py` will carry its own runtime assertion when it's built.

### (b) Success/recovery outcome definition

A retry counts as **recovered** if the payment reaches `status=success` within **72 hours** of the retry attempt (`recovery_window_hours` in `sim_config.yaml`). Chosen (not sourced) to be short enough to keep the simulated timeline and evaluation tractable within a 3-week build, while still being long enough to show the transient-failure and insufficient-funds recovery patterns above. The retry-timing menu the Phase 3 scheduler chooses from is discrete: **now / +6h / +24h / +72h** — a fixed candidate offset list rather than a continuous timestamp, chosen for implementation and evaluation simplicity (a real scheduler wouldn't pick arbitrary continuous timestamps either).

### (c) Treatment assignment logic

For the simulated **historical/training period**, retry-vs-no-retry is assigned **randomly, 50/50, per failed attempt** (`treatment_assignment` in `sim_config.yaml`), computed as a deterministic hash of `order_id` (`assignment.py`) rather than drawn from RNG call order — every assignment is independently recomputable and auditable from its `order_id` alone. "Treatment" is defined as an immediate retry (offset 0h); "control" is no retry.

This is deliberately unconfounded: we simulate as if the historical data-generating policy were a randomized retry policy, which is a real practice some companies use specifically to build unbiased causal training data. The alternative — a rule-based historical policy (e.g. "always retry once within 1h") — was rejected for Phase 1 because it introduces confounding that would require propensity-score correction to use safely in the T-learner, adding real complexity without a corresponding lesson for this build's timeline.

**This mechanism applies only to the historical/training data.** At evaluation/deployment time (Phase 3+), retry decisions come from the policy engine (uplift-ranked, budget-constrained), not randomization — the whole point of the project is comparing that learned policy against baselines. The two must not be conflated: training-time randomization avoids confounding the model; evaluation-time policy decisions are what's actually being tested. The chronological train/validation/test split (CLAUDE.md non-negotiable #6: "split by time, not randomly") is applied on top of this randomized-label population — never train on a time window later than what's evaluated.

### (d) Addendum, Phase 2: timeout ambiguity / double-charge near-misses

Frozen 2026-08-31, Phase 2. For `taxonomy.TIMEOUT_AMBIGUOUS_CODES` only (`payment_timed_out`, `upi_timeout`, `netbanking_session_timeout`) — codes where the gateway genuinely could not confirm the outcome, as opposed to a definite decline — a small fraction (`ambiguous_timeout_success_rate: 0.05` in `sim_config.yaml`, illustrative) of these attempts are flagged `actually_succeeded_silently=True` in hidden ground truth: the charge went through despite being reported as failed. This is the real-world phenomenon CLAUDE.md non-negotiable #2 ("reconcile before retry, always") exists to guard against, and it's what gives the evaluation harness's "double-charge near-misses" metric something concrete to count: a baseline that retries one of these attempts without reconciling first (none of the Phase 2 baselines reconcile — that service doesn't exist until Phase 5) produces a genuine near-miss, not a proxy. This also gives Phase 5's reconciler a concrete scenario to demonstrate against later.

This is additive to the Phase 1 freeze above, not a revision — everything already committed (the recovery curves, the 50k generated attempts) stays valid; this only adds one new hidden field, scoped to three specific codes.

### (e) Addendum, Phase 3: 5-arm treatment assignment (retry timing)

Frozen 2026-08-31, Phase 3. (c) above only randomized retry-vs-no-retry (2 arms), which is enough to train a causal model of *whether* to retry, but not *when* — there was never a logged experiment for "retry at +6h" vs "retry at +24h", so no data existed to learn timing without peeking at the hidden curve. `simulator/assignment.py` now randomizes uniformly across **5 arms**: `no_retry`, `retry_0h`, `retry_6h`, `retry_24h`, `retry_72h` (still a deterministic hash of `order_id`, salted `v2` to mark the mechanism change explicitly rather than silently reinterpreting old draws). Each failed attempt's single observed outcome is now drawn from whichever arm it landed in, using that arm's true probability from the same hidden recovery curve as before.

This lets `ml/train_uplift.py` train a T-learner where the "treated" model takes offset as a feature (predicting `P(recover | X, offset)` for any of the 4 offsets) and the "control" model predicts `P(recover | X, no_retry)` — still two XGBoost models, per CLAUDE.md, just with the treated model covering the full timing menu instead of only "now". `uplift(now) = treated(X, 0) - control(X)`; `uplift(best) = max` over the 4 offsets.

Additive, not a revision of (a)/(b)/(d) above — the recovery curves, decline taxonomy, and double-charge mechanism are unchanged. Only the *assignment* mechanism and the resulting `observed_outcome`/`assignment` fields in `ground_truth.jsonl` changed shape, and the 50k dataset was regenerated accordingly (exact per-attempt values differ from the Phase 1/2 runs; the distributional properties documented above — method mix, decline rates, recovery curves — do not).

## Uplift model

Frozen 2026-08-31, Phase 3. Implementation: `backend/ml/{features,train_uplift,evaluate}.py`, `backend/app/services/{scorer,scheduler}.py`.

**T-learner**: two XGBoost classifiers. `control_model` predicts P(recover | X) trained on the `no_retry` arm's observed outcomes; `treated_model` predicts P(recover | X, offset_hours) trained on the pooled `retry_0h/6h/24h/72h` arms, with `offset_hours` as a feature. `uplift(X, offset) = treated(X, offset) - control(X)`. Both are plain XGBoost defaults (200 trees, depth 4, lr 0.1) — no hyperparameter search, given the timeline; a documented limitation, not an oversight.

**Features** (`ml/features.py`): `amount`, `method`, `issuer`, `error_code`, `cause_family` (derived from `error_code` via `taxonomy.py`, same as the rule-based baseline), `hour_of_day`, `day_of_week`, plus `offset_hours` for the treated model only. `build_features()` asserts its input never carries a `ground_truth.jsonl` key — see the module docstring. Categorical columns use a *fixed* vocabulary (drawn from `sim_config.yaml`/`taxonomy.py`, not whatever appears in a given split) so encoding is identical at training and inference time.

**Chronological split**: first 60 days train (4,438 failed attempts), next 15 days validation (1,148), final 15 days test (1,107) — held out completely from training, per CLAUDE.md non-negotiable #6.

**Honest result, not spun**: at the same budget as `rule_based` on held-out test data (863 retries, ₹1,726 cost), `uplift_ranked` recovers ₹599,005 vs `rule_based`'s ₹602,287 — essentially tied, marginally behind. `uplift@20%` is 0.76 and the Qini curve is positive and rising throughout, meaning the model's *ranking* of who to retry is genuinely informative — it's just that `rule_based`'s hand-coded routing (skip hard declines, wait out outages, time insufficient-funds retries) already captures most of what's learnable from ~4,400 training examples, so the model doesn't clearly beat it at this budget on this test slice. The likely limiting factor is test-set size (1,107 attempts is small for stable causal-effect estimation) rather than a flaw in the approach — see `docs/DECISIONS.md`. This is reported as-is per CLAUDE.md non-negotiable #7: never tune the simulator to make the model win.

**Budget-constrained ranking** (`score_uplift_policy` in `ml/evaluate.py`): every held-out attempt gets scored for uplift at each candidate offset (from the *model*, never the hidden curve); attempts are ranked by best predicted uplift descending; the top `budget` attempts with positive predicted uplift are retried at their predicted-best offset. The *actual* recovered value is then computed from the hidden ground-truth probability at that chosen offset, not the model's own belief — the model picks the action, ground truth grades it. This is the same principle Phase 2's baseline scoring already followed.

## Policy

Frozen 2026-09-01, Phase 5. Implementation: `backend/app/services/{reconciler,diagnoser,policy_engine,action_service}.py`, `backend/app/config/policy.yaml`, `backend/app/schemas/diagnosis.py`.

**Reconciliation runs first, always** (CLAUDE.md non-negotiable #2). The gateway lookup is mocked — no real Razorpay in this build — but the mock isn't a coin flip: for timeout-type codes (`taxonomy.TIMEOUT_AMBIGUOUS_CODES`) it consults the simulator's hidden `actually_succeeded_silently` ground truth (frozen in (d) above) for whether the charge actually went through despite being reported failed. This is not model leakage — a real gateway API call would honestly return the same answer for a real payment; the mock just answers from a file instead of a network request, and nothing here feeds the uplift model. For every other code, reconciliation is a pass-through confirming the already-known `failed` status.

**LLM provider is Groq, not Anthropic** — CLAUDE.md's stated stack, changed by explicit user direction this session; see `docs/DECISIONS.md`. The diagnoser's job is strictly classification (CLAUDE.md non-negotiable #1: the LLM never makes money decisions) — `root_cause`, `cause_family`, `is_transient`, `confidence`, Pydantic-validated, retried up to 2 times on invalid/unparseable output before raising. Verified live against the real API for both a transient and a hard-decline example.

**The policy engine's safety-critical block check never trusts the LLM's own classification** — it uses the deterministic `taxonomy.py` lookup on the attempt's `error_code` instead, passed in as a separate `cause_family` argument. This was a live-testing finding, not a design choice made in the abstract: the real Groq model disagreed with the taxonomy on a real example (classified a `card_or_account_issue` hard decline as `customer_error`), and the first version of the policy engine would have let that retry through. See `docs/DECISIONS.md` for the full story — it's the clearest illustration in this project of why CLAUDE.md's non-negotiable #1 matters operationally, not just architecturally.

**`policy.yaml` v1 rules**, evaluated in order, any firing blocks the retry:
1. `require_reconciliation` — must be known-failed (see above)
2. `block_cause_families` — `card_or_account_issue`, `risk_fraud` never retried, regardless of predicted uplift (deterministic taxonomy classification, not the LLM's)
3. `require_diagnosis_confidence` — LLM confidence must be ≥ 0.5, independent of the block check above; a low-confidence diagnosis signals an edge case that deserves review, not automated action
4. `require_positive_uplift` — delegates to `scheduler.schedule()`'s existing `uplift_best > 0` check
5. `max_api_retries: 2` — not a policy_engine gate; enforced by `action_service` on the infra-level HTTP call (see below)

**Idempotency** (CLAUDE.md non-negotiable #3): `idempotency_key = sha256(payment_id + action_type + scheduled_time + policy_version)`. `action_service.execute_retry()` checks the `actions` table for an existing row with the same key before ever calling the gateway, and returns that row's result instead of re-executing — the actual "safe to call twice" guarantee, not just a deterministic key.

**Retry budget** (CLAUDE.md non-negotiable #4): max 2 API retries on 5xx, exponential backoff (0.5s, 1s) between attempts, 3 total attempts max, then `outcome="retry_exhausted"` — an infra-level cap on the HTTP call itself, distinct from `policy_engine`'s business-level decision about whether to retry the payment at all. Verified live with a client that always returns 503: 3 attempts, `retry_exhausted`, no infinite loop.

**Every decision is persisted**, not just approved retries — see `docs/DECISIONS.md`. A `decisions` row exists for every attempt that reaches the policy engine, whichever way it went.

## Evaluation

Frozen 2026-08-31, Phase 2. Implementation: `backend/ml/{baselines,evaluate}.py`.

**Scoring is expected-value, not a single stochastic realization.** Every policy's ₹ recovered, retry count, etc. are computed analytically from the true recovery probabilities in `ground_truth.jsonl` (probability-weighted), not by sampling one 0/1 outcome per attempt. This matches the project's actual thesis — optimizing for *expected* incremental revenue — and keeps the comparison table deterministic and reproducible rather than dominated by sampling noise across ~6,665 failed attempts split five ways by cause family. For a sequence of retries (e.g. retry-3x), the standard sequential-Bernoulli-trial formula is used: attempt *i* is only reached (in expectation) if all prior attempts in the plan failed, so expected retries executed and expected probability of eventual recovery both account for early stopping at first success.

**The four baselines:**
- **do-nothing**: never retries. Its ₹ recovered is *not* zero — it's the natural/unprompted recovery rate (`p_recover_unretried`), since some customers or banks self-resolve without our intervention. This is the correct counterfactual baseline: the project's thesis is about *incremental* revenue over this natural rate, not revenue over literally nothing.
- **retry-once**: retries every failed attempt exactly once, immediately (offset 0h).
- **retry-3x**: retries at 0h, +6h, +24h (the first three of the four candidate offsets), stopping at first success, with `patience_decay.per_attempt_multiplier` (0.75, from `sim_config.yaml`) compounding on each successive attempt's probability — modeling customer/system fatigue.
- **rule-based**: routes by `cause_family` — never retries `card_or_account_issue` or `risk_fraud` (hard declines, retrying wastes money); retries `technical_bank_downtime` at +6h (wait out the outage); `insufficient_funds` at +72h (payday effect); `customer_error` at +24h (next-day nudge). `cause_family` here is a deterministic lookup from `error_code` via `taxonomy.py` — the same static, documented classification used to label the simulated data, not simulator hidden state. It's the kind of lookup a real integration would derive from its own PSP's decline-code docs, no ML/LLM required. This is a distinct thing from the hidden recovery-probability *curve*, which stays off-limits.

**Customer contacts** = expected retries executed against `customer_error`-family attempts specifically — the one cause family where "retry" means re-prompting the customer (they need to redo their OTP/CVV/UPI PIN) rather than a silent gateway-side re-authorization, per the causal design in (a) above.

**Cost per ₹ recovered** = (expected total retries × `retry_cost_inr`, illustrative 2.0 in `sim_config.yaml`) ÷ ₹ recovered.

**Double-charge near-misses** = count (not expected value — this is a concrete, already-resolved fact per attempt from ground truth, not a live probability) of attempts where `actually_succeeded_silently=True` *and* the policy chose to retry at all. The first retry in any plan is always executed before any check, so if the attempt had already silently succeeded, retrying it is a real near-miss the moment the policy decides to retry — see (d) above.

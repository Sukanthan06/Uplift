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

## Policy

_TBD — Phase 5._

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

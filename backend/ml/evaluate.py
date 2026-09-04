"""Evaluation harness: scores baseline retry policies AND the trained uplift
model against the simulator's hidden ground truth, prints comparison tables,
and computes a Qini curve / uplift@k on held-out data.

Two different evaluation modes live in this file, and they must not be
confused:
  - Baseline/uplift-ranked POLICY SCORING (score_policy, score_uplift_policy)
    uses the hidden ground-truth probability curve to compute the expected
    ₹ outcome of whichever action a policy chose. This is legitimate: the
    curve is used to grade a decision after the fact, never to make it.
  - Qini/uplift@k uses ONLY each held-out test attempt's single OBSERVED
    outcome under its historically-assigned arm -- exactly what a real
    offline uplift evaluation has access to, with no ground-truth curve
    involved at all. This is the standard, more rigorous method and is
    deliberately independent of the simulator's hidden state.

See docs/ASSUMPTIONS.md ("Evaluation") for full methodology.
"""

from __future__ import annotations

import json
import pickle
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import xgboost as xgb

from ml.baselines import BASELINES, RetryPlan
from ml.features import build_features, to_dataframe
from ml.train_uplift import MODEL_DIR, TRAIN_DAYS, VAL_DAYS
from simulator.generator import load_config

GROUND_TRUTH_PATH = Path(__file__).parent.parent / "simulator" / "output" / "ground_truth.jsonl"


@dataclass(frozen=True)
class AttemptRecord:
    order_id: str
    amount: float
    method: str
    issuer: str | None
    error_code: str
    cause_family: str
    created_at: datetime
    p_recover_unretried: float
    p_recover_offsets: dict[int, float]
    actually_succeeded_silently: bool
    assigned_arm: str
    observed_outcome: bool


@dataclass(frozen=True)
class PolicyScore:
    recovered_inr: float
    retry_count: float
    cost_inr: float
    cost_per_inr_recovered: float
    customer_contacts: float
    double_charge_near_misses: int


def load_attempts() -> list[AttemptRecord]:
    """Join every failed payment_attempts row (Postgres) against the
    simulator's hidden ground-truth JSONL by order_id, for scoring only --
    never for training (see ml/train_uplift.py's load_labeled_attempts for
    the training-time equivalent, which never touches p_recover_*)."""
    from app.db import SessionLocal
    from app.models import PaymentAttempt

    if not GROUND_TRUTH_PATH.exists():
        raise FileNotFoundError(
            f"{GROUND_TRUTH_PATH} not found -- run `python -m simulator.generator` first"
        )

    ground_truth_by_order = {}
    with GROUND_TRUTH_PATH.open() as f:
        for line in f:
            gt = json.loads(line)
            ground_truth_by_order[gt["order_id"]] = gt

    session = SessionLocal()
    try:
        rows = session.query(PaymentAttempt).filter(PaymentAttempt.status == "failed").all()
        attempts = []
        for row in rows:
            gt = ground_truth_by_order.get(row.order_id)
            if gt is None:
                continue  # failed attempt from a different generator run than the ground truth file
            attempts.append(
                AttemptRecord(
                    order_id=row.order_id,
                    amount=float(row.amount),
                    method=row.method,
                    issuer=row.issuer,
                    error_code=row.error_code,
                    cause_family=gt["cause_family"],
                    created_at=row.created_at,
                    p_recover_unretried=gt["p_recover_unretried"],
                    p_recover_offsets={int(k): v for k, v in gt["p_recover_offsets"].items()},
                    actually_succeeded_silently=gt.get("actually_succeeded_silently", False),
                    assigned_arm=gt["assignment"]["assigned_arm"],
                    observed_outcome=gt["observed_outcome"],
                )
            )
        return attempts
    finally:
        session.close()


def test_split(attempts: list[AttemptRecord], cfg: dict) -> list[AttemptRecord]:
    """The same chronological test-set boundary train_uplift.py holds out --
    never scored against during training, so this is honest out-of-sample
    evaluation."""
    window_start = datetime.fromisoformat(cfg["window"]["start"].replace("Z", "+00:00"))
    val_end = window_start + timedelta(days=TRAIN_DAYS + VAL_DAYS)
    return [a for a in attempts if a.created_at >= val_end]


def _as_feature_dict(attempt: AttemptRecord) -> dict[str, Any]:
    return {
        "amount": attempt.amount,
        "method": attempt.method,
        "issuer": attempt.issuer,
        "error_code": attempt.error_code,
        "created_at": attempt.created_at,
    }


def load_models() -> tuple[xgb.XGBClassifier, xgb.XGBClassifier]:
    """Unpickle the (control, treated) models train_uplift.py saved."""
    with (MODEL_DIR / "control_model.pkl").open("rb") as f:
        control_model = pickle.load(f)
    with (MODEL_DIR / "treated_model.pkl").open("rb") as f:
        treated_model = pickle.load(f)
    return control_model, treated_model


def _sequential_outcome(probabilities: list[float]) -> tuple[float, float]:
    """Expected (P(recovered by end of sequence), retries actually executed)
    for a stop-at-first-success retry sequence with per-step probabilities."""
    still_going = 1.0  # P(reached this attempt, i.e. every prior attempt failed)
    p_recovered = 0.0
    expected_retries = 0.0
    for p in probabilities:
        expected_retries += still_going
        p_recovered += still_going * p
        still_going *= 1 - p
    return p_recovered, expected_retries


def score_policy(attempts: list[AttemptRecord], plan_for: RetryPlan, cfg: dict) -> PolicyScore:
    """Score a baseline policy (do_nothing/retry_once/retry_3x/rule_based)
    against the hidden ground-truth curve: expected recovered INR, retries
    spent, cost, and customer contacts, grading the policy's chosen action
    after the fact -- never used to make the decision itself."""
    decay = cfg["patience_decay"]["per_attempt_multiplier"]
    retry_cost = cfg["retry_cost_inr"]

    recovered_inr = 0.0
    total_retries = 0.0
    customer_contacts = 0.0
    double_charge_near_misses = 0

    for attempt in attempts:
        plan = plan_for(attempt.cause_family)
        if not plan.offsets_hours:
            recovered_inr += attempt.amount * attempt.p_recover_unretried
            continue

        if attempt.actually_succeeded_silently:
            double_charge_near_misses += 1

        raw_probs = [attempt.p_recover_offsets[h] for h in plan.offsets_hours]
        decayed_probs = [p * (decay**i) for i, p in enumerate(raw_probs)]
        p_recovered, expected_retries = _sequential_outcome(decayed_probs)

        recovered_inr += attempt.amount * p_recovered
        total_retries += expected_retries
        if attempt.cause_family == "customer_error":
            customer_contacts += expected_retries

    cost_inr = total_retries * retry_cost
    cost_per_inr_recovered = cost_inr / recovered_inr if recovered_inr else float("inf")

    return PolicyScore(
        recovered_inr=recovered_inr,
        retry_count=total_retries,
        cost_inr=cost_inr,
        cost_per_inr_recovered=cost_per_inr_recovered,
        customer_contacts=customer_contacts,
        double_charge_near_misses=double_charge_near_misses,
    )


def _predict_uplift_grid(
    attempts: list[AttemptRecord],
    control_model: xgb.XGBClassifier,
    treated_model: xgb.XGBClassifier,
    offsets_hours: list[int],
):
    """Vectorized: one predict_proba call for control, one for all
    (attempt, offset) pairs. Returns (control_p, treated_p) where
    treated_p[i] is an array of predicted probabilities, one per offset."""
    base_dicts = [_as_feature_dict(a) for a in attempts]

    control_features = to_dataframe([build_features(d) for d in base_dicts])
    control_p = control_model.predict_proba(control_features)[:, 1]

    treated_rows = [build_features(d, offset_hours=o) for d in base_dicts for o in offsets_hours]
    treated_features = to_dataframe(treated_rows)
    treated_p_flat = treated_model.predict_proba(treated_features)[:, 1]

    n_offsets = len(offsets_hours)
    treated_p = [treated_p_flat[i * n_offsets : (i + 1) * n_offsets] for i in range(len(attempts))]
    return control_p, treated_p


def score_uplift_policy(
    attempts: list[AttemptRecord],
    control_model: xgb.XGBClassifier,
    treated_model: xgb.XGBClassifier,
    budget: int,
    cfg: dict,
) -> PolicyScore:
    """Budget-constrained, uplift-ranked policy. The MODEL's predicted
    uplift picks which attempts to retry and at what offset (ranked
    descending, top `budget` with positive predicted uplift); the ACTUAL
    recovered value is then computed from the hidden ground-truth
    probability at that chosen offset -- the model grades its own choice of
    action, never its own belief about the outcome."""
    offsets_hours = cfg["retry_offsets_hours"]
    retry_cost = cfg["retry_cost_inr"]

    control_p, treated_p = _predict_uplift_grid(
        attempts, control_model, treated_model, offsets_hours
    )

    decisions = []  # (index, best_offset, best_predicted_uplift)
    for i in range(len(attempts)):
        uplift_per_offset = treated_p[i] - control_p[i]
        best_j = int(uplift_per_offset.argmax())
        decisions.append((i, offsets_hours[best_j], float(uplift_per_offset[best_j])))

    decisions.sort(key=lambda t: t[2], reverse=True)
    chosen = {i: offset for i, offset, uplift in decisions[:budget] if uplift > 0}

    recovered_inr = 0.0
    total_retries = 0.0
    customer_contacts = 0.0
    double_charge_near_misses = 0

    for i, attempt in enumerate(attempts):
        if i not in chosen:
            recovered_inr += attempt.amount * attempt.p_recover_unretried
            continue
        if attempt.actually_succeeded_silently:
            double_charge_near_misses += 1
        p_true = attempt.p_recover_offsets[chosen[i]]
        recovered_inr += attempt.amount * p_true
        total_retries += 1
        if attempt.cause_family == "customer_error":
            customer_contacts += 1

    cost_inr = total_retries * retry_cost
    cost_per_inr_recovered = cost_inr / recovered_inr if recovered_inr else float("inf")

    return PolicyScore(
        recovered_inr=recovered_inr,
        retry_count=total_retries,
        cost_inr=cost_inr,
        cost_per_inr_recovered=cost_per_inr_recovered,
        customer_contacts=customer_contacts,
        double_charge_near_misses=double_charge_near_misses,
    )


def _rank_by_predicted_uplift(
    attempts: list[AttemptRecord],
    control_model: xgb.XGBClassifier,
    treated_model: xgb.XGBClassifier,
    cfg: dict,
) -> list[tuple[float, bool, bool]]:
    """(predicted_uplift_best, was_treated, observed_outcome) per attempt,
    sorted descending by predicted uplift. was_treated/observed_outcome use
    only the single arm each attempt was historically, randomly assigned to
    -- no ground-truth curve involved, matching how a real offline uplift
    evaluation works."""
    offsets_hours = cfg["retry_offsets_hours"]
    control_p, treated_p = _predict_uplift_grid(
        attempts, control_model, treated_model, offsets_hours
    )

    scored = []
    for i, attempt in enumerate(attempts):
        uplift_best = float((treated_p[i] - control_p[i]).max())
        was_treated = attempt.assigned_arm != "no_retry"
        scored.append((uplift_best, was_treated, attempt.observed_outcome))
    scored.sort(key=lambda t: t[0], reverse=True)
    return scored


def qini_curve(
    attempts: list[AttemptRecord],
    control_model: xgb.XGBClassifier,
    treated_model: xgb.XGBClassifier,
    cfg: dict,
    n_points: int = 20,
) -> list[tuple[float, float]]:
    """Qini(k) = (treated successes in top-k) - (control successes in top-k)
    * (n_treated_topk / n_control_topk), at n_points cumulative fractions k
    of held-out attempts ranked by predicted uplift."""
    scored = _rank_by_predicted_uplift(attempts, control_model, treated_model, cfg)
    n = len(scored)
    step = max(1, n // n_points)

    points = []
    cum_treated_y = cum_treated_n = cum_control_y = cum_control_n = 0
    for idx, (_, was_treated, outcome) in enumerate(scored, start=1):
        if was_treated:
            cum_treated_n += 1
            cum_treated_y += int(outcome)
        else:
            cum_control_n += 1
            cum_control_y += int(outcome)
        if idx % step == 0 or idx == n:
            qini = (
                cum_treated_y - cum_control_y * (cum_treated_n / cum_control_n)
                if cum_control_n > 0
                else float(cum_treated_y)
            )
            points.append((idx / n, qini))
    return points


def uplift_at_k(
    attempts: list[AttemptRecord],
    control_model: xgb.XGBClassifier,
    treated_model: xgb.XGBClassifier,
    cfg: dict,
    k_fraction: float = 0.2,
) -> float:
    """Mean observed outcome among treated attempts minus mean observed
    outcome among control attempts, within the top k_fraction of held-out
    attempts ranked by predicted uplift."""
    scored = _rank_by_predicted_uplift(attempts, control_model, treated_model, cfg)
    top = scored[: max(1, int(len(scored) * k_fraction))]
    treated_outcomes = [outcome for _, was_treated, outcome in top if was_treated]
    control_outcomes = [outcome for _, was_treated, outcome in top if not was_treated]
    if not treated_outcomes or not control_outcomes:
        return float("nan")
    return (sum(treated_outcomes) / len(treated_outcomes)) - (
        sum(control_outcomes) / len(control_outcomes)
    )


def print_comparison_table(scores: dict[str, PolicyScore]) -> None:
    headers = [
        "policy",
        "recovered (INR)",
        "retries",
        "cost (INR)",
        "cost / INR recovered",
        "customer contacts",
        "double-charge near-misses",
    ]
    rows = [
        [
            name,
            f"{s.recovered_inr:,.0f}",
            f"{s.retry_count:,.1f}",
            f"{s.cost_inr:,.0f}",
            f"{s.cost_per_inr_recovered:.4f}",
            f"{s.customer_contacts:,.1f}",
            str(s.double_charge_near_misses),
        ]
        for name, s in scores.items()
    ]
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    line = " | ".join(h.ljust(w) for h, w in zip(headers, widths, strict=True))
    print(line)
    print("-" * len(line))
    for row in rows:
        print(" | ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)))


def run() -> dict[str, PolicyScore]:
    """Phase 2: baselines only, all failed attempts, no ML."""
    cfg = load_config()
    attempts = load_attempts()
    scores = {name: score_policy(attempts, policy, cfg) for name, policy in BASELINES.items()}
    print(f"{len(attempts)} failed attempts evaluated\n")
    print_comparison_table(scores)
    return scores


def run_phase3() -> dict[str, PolicyScore]:
    """Phase 3: baselines + uplift-ranked policy, scored on the held-out
    chronological test split only -- a fair, honest, out-of-sample
    comparison. Budget is set to match rule_based's retry count on this same
    test slice, so "uplift-ranked" and "rule-based" spend the same money."""
    cfg = load_config()
    attempts = test_split(load_attempts(), cfg)
    control_model, treated_model = load_models()

    scores = {name: score_policy(attempts, policy, cfg) for name, policy in BASELINES.items()}
    budget = round(scores["rule_based"].retry_count)
    scores["uplift_ranked"] = score_uplift_policy(
        attempts, control_model, treated_model, budget, cfg
    )

    print(f"{len(attempts)} held-out test attempts evaluated (budget={budget})\n")
    print_comparison_table(scores)

    print(f"\nuplift@20%: {uplift_at_k(attempts, control_model, treated_model, cfg, 0.2):.4f}")
    qini = qini_curve(attempts, control_model, treated_model, cfg)
    print("qini curve (k, qini):")
    for k, q in qini:
        print(f"  {k:.2f}  {q:.2f}")
    return scores


if __name__ == "__main__":
    run()

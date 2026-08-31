"""Evaluation harness: scores baseline retry policies against the
simulator's hidden ground truth and prints a comparison table.

No uplift model yet -- this establishes the honest baseline comparison that
Phase 3's learned policy will later have to beat. See docs/ASSUMPTIONS.md
("Evaluation") for the scoring methodology and metric definitions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ml.baselines import BASELINES, RetryPlan
from simulator.generator import load_config

GROUND_TRUTH_PATH = Path(__file__).parent.parent / "simulator" / "output" / "ground_truth.jsonl"


@dataclass(frozen=True)
class AttemptRecord:
    order_id: str
    amount: float
    cause_family: str
    p_recover_unretried: float
    p_recover_offsets: dict[int, float]
    actually_succeeded_silently: bool


@dataclass(frozen=True)
class PolicyScore:
    recovered_inr: float
    retry_count: float
    cost_inr: float
    cost_per_inr_recovered: float
    customer_contacts: float
    double_charge_near_misses: int


def load_attempts() -> list[AttemptRecord]:
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
                    cause_family=gt["cause_family"],
                    p_recover_unretried=gt["p_recover_unretried"],
                    p_recover_offsets={int(k): v for k, v in gt["p_recover_offsets"].items()},
                    actually_succeeded_silently=gt.get("actually_succeeded_silently", False),
                )
            )
        return attempts
    finally:
        session.close()


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
    cfg = load_config()
    attempts = load_attempts()
    scores = {name: score_policy(attempts, policy, cfg) for name, policy in BASELINES.items()}
    print(f"{len(attempts)} failed attempts evaluated\n")
    print_comparison_table(scores)
    return scores


if __name__ == "__main__":
    run()

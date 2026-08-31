"""Generates the simulated payment-attempt population and, for every failed
attempt, its hidden ground-truth recovery-probability curve.

Ground truth is written to a file OUTSIDE the application database/schema on
purpose: no application code path (reconciler, policy_engine, scorer, ...)
can import or query it. That's the structural enforcement of CLAUDE.md's
"the uplift model must not see the simulator's hidden state" rule -- only
ml/train_uplift.py and ml/evaluate.py (Phase 3) are meant to read it, to
construct training labels and score honestly, never as a model feature.

See docs/ASSUMPTIONS.md for the causal mechanism, outcome definition, and
treatment assignment logic this implements.
"""

from __future__ import annotations

import json
import math
import random
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from simulator import taxonomy
from simulator.assignment import assign_treatment

CONFIG_PATH = Path(__file__).parent / "sim_config.yaml"
BANK_MEDIATED_METHODS = ("card", "netbanking", "upi")


def load_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text())


@dataclass(frozen=True)
class IssuerOutage:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class GeneratedRow:
    payment_attempt: dict
    ground_truth: dict | None  # None for successful attempts -- nothing to retry


def _build_outage_calendars(
    rng: random.Random,
    issuers: list[str],
    window_start: datetime,
    window_end: datetime,
    cfg: dict,
) -> dict[str, list[IssuerOutage]]:
    calendars: dict[str, list[IssuerOutage]] = {issuer: [] for issuer in issuers}
    mean_gap_days = cfg["outage"]["mean_days_between_outages"]
    dur_cfg = cfg["outage"]["duration_hours"]
    for issuer in issuers:
        t = window_start
        while t < window_end:
            t = t + timedelta(days=rng.expovariate(1 / mean_gap_days))
            if t >= window_end:
                break
            duration_hours = min(
                math.exp(rng.gauss(dur_cfg["mean_log"], dur_cfg["sigma_log"])),
                dur_cfg["max_hours"],
            )
            calendars[issuer].append(IssuerOutage(t, t + timedelta(hours=duration_hours)))
    return calendars


def _is_down(outages: list[IssuerOutage], at: datetime) -> bool:
    return any(o.start <= at <= o.end for o in outages)


def _recovery_probabilities(
    cause_family: str,
    created_at: datetime,
    issuer_outages: list[IssuerOutage],
    offsets_hours: list[int],
) -> tuple[float, dict[int, float]]:
    """Hidden ground truth: (p_recover_unretried, {offset_h: p_recover_if_retried_at_offset})."""
    if cause_family == "technical_bank_downtime":
        p_unretried = 0.05
        offsets = {
            h: (0.05 if _is_down(issuer_outages, created_at + timedelta(hours=h)) else 0.85)
            for h in offsets_hours
        }
        return p_unretried, offsets
    if cause_family == "insufficient_funds":
        curve = {0: 0.10, 6: 0.15, 24: 0.30, 72: 0.55}
        return 0.08, {h: curve.get(h, 0.10) for h in offsets_hours}
    if cause_family == "card_or_account_issue":
        return 0.02, dict.fromkeys(offsets_hours, 0.04)
    if cause_family == "customer_error":
        curve = {0: 0.35, 6: 0.38, 24: 0.42, 72: 0.45}
        return 0.05, {h: curve.get(h, 0.35) for h in offsets_hours}
    if cause_family == "risk_fraud":
        return 0.03, dict.fromkeys(offsets_hours, 0.06)
    raise ValueError(f"unknown cause_family {cause_family!r}")


def generate(config: dict | None = None) -> list[GeneratedRow]:
    cfg = config or load_config()
    rng = random.Random(cfg["random_seed"])

    window_start = datetime.fromisoformat(cfg["window"]["start"].replace("Z", "+00:00"))
    window_days = cfg["window"]["days"]
    window_end = window_start + timedelta(days=window_days)

    methods = list(cfg["method_mix"].keys())
    method_weights = list(cfg["method_mix"].values())
    issuers = cfg["issuers"]
    offsets_hours = cfg["retry_offsets_hours"]
    treatment_probability = cfg["treatment_assignment"]["probability"]
    amount_cfg = cfg["amount"]

    outage_calendars = _build_outage_calendars(rng, issuers, window_start, window_end, cfg)

    rows: list[GeneratedRow] = []
    for _ in range(cfg["volume"]["n_attempts"]):
        method = rng.choices(methods, weights=method_weights, k=1)[0]
        created_at = window_start + timedelta(seconds=rng.uniform(0, window_days * 86400))
        issuer = rng.choice(issuers) if method in BANK_MEDIATED_METHODS else None
        issuer_outages = outage_calendars.get(issuer, []) if issuer else []
        is_down_now = _is_down(issuer_outages, created_at)

        amount = min(
            max(rng.lognormvariate(amount_cfg["mu"], amount_cfg["sigma"]), amount_cfg["min"]),
            amount_cfg["max"],
        )
        order_id = f"order_{uuid.UUID(int=rng.getrandbits(128)).hex}"
        customer_id = f"cust_{uuid.UUID(int=rng.getrandbits(128)).hex[:16]}"

        base_rate = cfg["base_decline_rate"][method]
        effective_rate = min(base_rate * 4, 0.9) if is_down_now else base_rate
        failed = rng.random() < effective_rate

        if not failed:
            rows.append(
                GeneratedRow(
                    payment_attempt={
                        "order_id": order_id,
                        "customer_id": customer_id,
                        "amount": round(amount, 2),
                        "method": method,
                        "psp": "razorpay",
                        "issuer": issuer,
                        "status": "success",
                        "error_code": None,
                        "error_desc": None,
                        "attempt_no": 1,
                        "parent_attempt_id": None,
                        "created_at": created_at,
                    },
                    ground_truth=None,
                )
            )
            continue

        codes = taxonomy.codes_for_method(method)
        outage_multiplier = cfg["outage"]["technical_decline_multiplier"]
        weights = [
            c.weight * (outage_multiplier if is_down_now and c.is_transient else 1.0) for c in codes
        ]
        decline = rng.choices(codes, weights=weights, k=1)[0]

        p_unretried, p_offsets = _recovery_probabilities(
            decline.cause_family, created_at, issuer_outages, offsets_hours
        )

        assignment = assign_treatment(order_id, treatment_probability)
        # Historical label: "treatment" = immediate retry (offset 0h). The
        # single observed outcome is drawn once, here, and fixed -- this is
        # the one potential outcome a real system would actually see; the
        # other remains counterfactual and lives only in ground_truth.
        if assignment.assigned_treatment == "treatment":
            observed_outcome = rng.random() < p_offsets[0]
        else:
            observed_outcome = rng.random() < p_unretried

        payment_attempt = {
            "order_id": order_id,
            "customer_id": customer_id,
            "amount": round(amount, 2),
            "method": method,
            "psp": "razorpay",
            "issuer": issuer,
            "status": "failed",
            "error_code": decline.code,
            "error_desc": decline.description,
            "attempt_no": 1,
            "parent_attempt_id": None,
            "created_at": created_at,
        }
        # Structural leakage guard: the row written to the application
        # schema must never carry hidden-state keys.
        hidden_keys = {"p_recover_unretried", "p_recover_offsets", "cause_family"}
        assert not hidden_keys & payment_attempt.keys()

        rows.append(
            GeneratedRow(
                payment_attempt=payment_attempt,
                ground_truth={
                    "order_id": order_id,
                    "cause_family": decline.cause_family,
                    "is_transient": decline.is_transient,
                    "p_recover_unretried": p_unretried,
                    "p_recover_offsets": p_offsets,
                    "assignment": asdict(assignment),
                    "observed_outcome": observed_outcome,
                },
            )
        )

    return rows


def run(output_dir: Path | None = None) -> None:
    from app.db import engine
    from app.models import PaymentAttempt

    cfg = load_config()
    rows = generate(cfg)

    output_dir = output_dir or Path(__file__).parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    ground_truth_path = output_dir / "ground_truth.jsonl"

    # Core-level executemany with a uniform column set per row (every dict
    # below always has all 12 keys, even when the value is None) so psycopg
    # can batch this as one real multi-row operation. The ORM's
    # bulk_insert_mappings instead varies the generated SQL per row when a
    # value is None -- one INSERT statement shape per distinct set of
    # non-null columns -- which serializes into ~50k single-row round trips.
    with engine.begin() as conn:
        conn.execute(PaymentAttempt.__table__.insert(), [row.payment_attempt for row in rows])

    with ground_truth_path.open("w") as gt_file:
        for row in rows:
            if row.ground_truth is not None:
                gt_file.write(json.dumps(row.ground_truth, default=str) + "\n")

    n_failed = sum(1 for r in rows if r.ground_truth is not None)
    print(f"generated {len(rows)} payment attempts ({n_failed} failed) -> Postgres")
    print(f"hidden ground truth for {n_failed} failed attempts -> {ground_truth_path}")


if __name__ == "__main__":
    run()

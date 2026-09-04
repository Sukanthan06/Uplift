"""T-learner uplift model: two XGBoost models trained on the simulator's
5-arm randomized historical data (see docs/ASSUMPTIONS.md (e)).

- control model: P(recover | X), trained on the no_retry arm's observed
  outcomes.
- treated model: P(recover | X, offset_hours), trained on the pooled
  retry_0h/6h/24h/72h arms' observed outcomes, offset as a feature.

uplift(X, offset) = treated(X, offset) - control(X). Trained only on each
attempt's single observed_outcome under its historically-assigned arm --
never on p_recover_unretried / p_recover_offsets, the hidden ground-truth
curve. Only ml/evaluate.py touches that curve, and only to score decisions,
never to train on them.

Chronological split (CLAUDE.md non-negotiable #6): train on the first 60
days, validate on the next 15, hold out the final 15 for test -- never train
on a time window later than what's evaluated.
"""

from __future__ import annotations

import json
import pickle
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import xgboost as xgb

from ml.features import build_features, to_dataframe
from simulator.generator import load_config

GROUND_TRUTH_PATH = Path(__file__).parent.parent / "simulator" / "output" / "ground_truth.jsonl"
MODEL_DIR = Path(__file__).parent / "output"

TRAIN_DAYS = 60
VAL_DAYS = 15  # remaining days (of sim_config.yaml's window.days) become test
RANDOM_SEED = 42  # matches sim_config.yaml's random_seed -- one seed, one story


@dataclass(frozen=True)
class LabeledAttempt:
    order_id: str
    features: dict
    assigned_arm: str
    observed_outcome: bool
    created_at: datetime


def load_labeled_attempts() -> list[LabeledAttempt]:
    """Join payment_attempts (Postgres) against the simulator's hidden
    ground-truth JSONL by order_id, producing one labeled example per
    failed attempt under its historically-assigned arm."""
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
        labeled = []
        for row in rows:
            gt = ground_truth_by_order.get(row.order_id)
            if gt is None:
                continue
            attempt = {
                "amount": row.amount,
                "method": row.method,
                "issuer": row.issuer,
                "error_code": row.error_code,
                "created_at": row.created_at,
            }
            arm = gt["assignment"]["assigned_arm"]
            offset = (
                None if arm == "no_retry" else int(arm.removeprefix("retry_").removesuffix("h"))
            )
            labeled.append(
                LabeledAttempt(
                    order_id=row.order_id,
                    features=build_features(attempt, offset_hours=offset),
                    assigned_arm=arm,
                    observed_outcome=gt["observed_outcome"],
                    created_at=row.created_at,
                )
            )
        return labeled
    finally:
        session.close()


def chronological_split(
    attempts: list[LabeledAttempt], cfg: dict
) -> tuple[list[LabeledAttempt], list[LabeledAttempt], list[LabeledAttempt]]:
    """Split by created_at, not randomly (CLAUDE.md non-negotiable #6):
    first TRAIN_DAYS train, next VAL_DAYS validate, the remainder test."""
    window_start = datetime.fromisoformat(cfg["window"]["start"].replace("Z", "+00:00"))
    train_end = window_start + timedelta(days=TRAIN_DAYS)
    val_end = train_end + timedelta(days=VAL_DAYS)
    train = [a for a in attempts if a.created_at < train_end]
    val = [a for a in attempts if train_end <= a.created_at < val_end]
    test = [a for a in attempts if a.created_at >= val_end]
    return train, val, test


def _fit(attempts: list[LabeledAttempt]) -> xgb.XGBClassifier:
    features = to_dataframe([a.features for a in attempts])
    labels = [int(a.observed_outcome) for a in attempts]
    model = xgb.XGBClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.1,
        enable_categorical=True,
        eval_metric="logloss",
        random_state=RANDOM_SEED,
    )
    model.fit(features, labels)
    return model


def train(attempts: list[LabeledAttempt] | None = None, cfg: dict | None = None) -> dict[str, int]:
    """Fit the T-learner's control and treated XGBoost models on a
    chronological train split and pickle both to MODEL_DIR. Returns split
    sizes for logging/reporting."""
    cfg = cfg or load_config()
    attempts = attempts if attempts is not None else load_labeled_attempts()
    train_set, val_set, test_set = chronological_split(attempts, cfg)

    control_train = [a for a in train_set if a.assigned_arm == "no_retry"]
    treated_train = [a for a in train_set if a.assigned_arm != "no_retry"]

    control_model = _fit(control_train)
    treated_model = _fit(treated_train)

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    with (MODEL_DIR / "control_model.pkl").open("wb") as f:
        pickle.dump(control_model, f)
    with (MODEL_DIR / "treated_model.pkl").open("wb") as f:
        pickle.dump(treated_model, f)

    return {
        "n_train": len(train_set),
        "n_val": len(val_set),
        "n_test": len(test_set),
        "n_control_train": len(control_train),
        "n_treated_train": len(treated_train),
    }


if __name__ == "__main__":
    stats = train()
    print(stats)
    print(f"models saved to {MODEL_DIR}")

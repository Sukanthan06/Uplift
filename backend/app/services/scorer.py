"""Loads the trained uplift model (ml/train_uplift.py's T-learner) and
scores a payment attempt: uplift(now) and uplift(best_time) among the
candidate retry offsets.

In production there is no hidden ground-truth curve to consult -- this is
the only signal available, exactly what the model was trained to work with
(ml/features.py). The retry-offset menu is read from sim_config.yaml for now
(single source of truth with the simulator that trained the model); Phase 5
should move it into app/config/policy.yaml once the policy engine owns it.
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import xgboost as xgb

from ml.features import build_features, to_dataframe
from ml.train_uplift import MODEL_DIR
from simulator.generator import load_config


@dataclass(frozen=True)
class UpliftScore:
    uplift_now: float
    uplift_best: float
    best_offset_hours: int


@lru_cache(maxsize=1)
def _load_models() -> tuple[xgb.XGBClassifier, xgb.XGBClassifier]:
    with (MODEL_DIR / "control_model.pkl").open("rb") as f:
        control_model = pickle.load(f)
    with (MODEL_DIR / "treated_model.pkl").open("rb") as f:
        treated_model = pickle.load(f)
    return control_model, treated_model


def score(attempt: dict[str, Any]) -> UpliftScore:
    """attempt must be a payment_attempts-shaped record (see
    ml/features.py). Returns uplift at offset 0h and at whichever candidate
    offset the model predicts is best."""
    control_model, treated_model = _load_models()
    offsets_hours = load_config()["retry_offsets_hours"]

    control_features = to_dataframe([build_features(attempt)])
    p_control = float(control_model.predict_proba(control_features)[0, 1])

    treated_rows = [build_features(attempt, offset_hours=h) for h in offsets_hours]
    treated_features = to_dataframe(treated_rows)
    p_treated = treated_model.predict_proba(treated_features)[:, 1]

    uplift_per_offset = p_treated - p_control
    best_idx = int(uplift_per_offset.argmax())

    return UpliftScore(
        uplift_now=float(uplift_per_offset[0]),
        uplift_best=float(uplift_per_offset[best_idx]),
        best_offset_hours=offsets_hours[best_idx],
    )

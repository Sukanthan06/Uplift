"""Feature builder for the uplift model.

Builds features strictly from a payment_attempts-shaped record -- amount,
method, issuer, error_code (all directly from the DB row), plus cause_family
(a deterministic taxonomy.py lookup on error_code, the same static PSP-doc
classification used to label the simulated data) and calendar features
derived from created_at. This is exactly what a real production event would
carry; none of it depends on the simulator's hidden recovery-probability
curve.

CLAUDE.md non-negotiable #6: the uplift model must not see the simulator's
hidden state. build_features() asserts its input never carries a
ground_truth.jsonl key, so a caller that accidentally merges the two record
types fails loudly instead of silently training on leaked probabilities.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from simulator import taxonomy
from simulator.generator import load_config

HIDDEN_STATE_KEYS = frozenset(
    {
        "p_recover_unretried",
        "p_recover_offsets",
        "cause_family",
        "is_transient",
        "assignment",
        "observed_outcome",
        "actually_succeeded_silently",
    }
)

CATEGORICAL_COLUMNS = ("method", "issuer", "error_code", "cause_family")
NUMERIC_COLUMNS = ("amount", "hour_of_day", "day_of_week")


def build_features(attempt: dict[str, Any], offset_hours: int | None = None) -> dict[str, Any]:
    """attempt must be a payment_attempts row (order_id, amount, method, psp,
    issuer, status, error_code, error_desc, attempt_no, parent_attempt_id,
    created_at) -- never a ground_truth.jsonl record or a merge of the two.
    """
    leaked = HIDDEN_STATE_KEYS & attempt.keys()
    assert not leaked, f"features.py received hidden simulator state: {leaked}"

    decline = taxonomy.get(attempt["error_code"], attempt["method"])
    created_at: datetime = attempt["created_at"]

    features: dict[str, Any] = {
        "amount": float(attempt["amount"]),
        "method": attempt["method"],
        "issuer": attempt["issuer"] or "none",
        "error_code": attempt["error_code"],
        "cause_family": decline.cause_family,
        "hour_of_day": created_at.hour,
        "day_of_week": created_at.weekday(),
    }
    if offset_hours is not None:
        features["offset_hours"] = offset_hours
    return features


# Fixed category vocabularies, not inferred from whatever happens to appear
# in a given train/val/test split -- so encoding is identical at training
# and inference time even if a category is rare or absent in one split.
_CFG = load_config()
_CATEGORY_VOCAB: dict[str, tuple[str, ...]] = {
    "method": tuple(_CFG["method_mix"].keys()),
    "issuer": (*tuple(_CFG["issuers"]), "none"),
    "error_code": tuple(sorted({c.code for c in taxonomy.DECLINE_TAXONOMY})),
    "cause_family": tuple(sorted(taxonomy.CAUSE_FAMILIES)),
}


def to_dataframe(feature_dicts: list[dict[str, Any]]) -> pd.DataFrame:
    """Feature dicts -> a DataFrame with fixed categorical dtypes, ready for
    XGBoost's native categorical support (enable_categorical=True)."""
    df = pd.DataFrame(feature_dicts)
    for col, vocab in _CATEGORY_VOCAB.items():
        if col in df.columns:
            df[col] = pd.Categorical(df[col], categories=vocab)
    return df

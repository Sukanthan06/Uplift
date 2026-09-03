from datetime import UTC, datetime

import numpy as np
import pytest

from app.services import scorer

_ATTEMPT = {
    "order_id": "order_test_1",
    "amount": 500.0,
    "method": "upi",
    "issuer": "HDFC Bank",
    "error_code": "upi_technical_failure",
    "created_at": datetime(2026, 1, 15, 12, 0, tzinfo=UTC),
}


class _FakeModel:
    def __init__(self, probabilities: list[float]) -> None:
        self._probabilities = probabilities

    def predict_proba(self, features):  # noqa: ANN001 - matches xgboost's signature
        n = len(features)
        p1 = np.array(self._probabilities[:n])
        return np.column_stack([1 - p1, p1])


def test_score_picks_offset_with_highest_uplift(monkeypatch: pytest.MonkeyPatch) -> None:
    offsets = [0, 6, 24, 72]
    control_model = _FakeModel([0.10])
    treated_model = _FakeModel([0.15, 0.20, 0.50, 0.30])

    monkeypatch.setattr(scorer, "_load_models", lambda: (control_model, treated_model))
    monkeypatch.setattr(scorer, "load_config", lambda: {"retry_offsets_hours": offsets})

    result = scorer.score(_ATTEMPT)

    assert result.uplift_now == pytest.approx(0.15 - 0.10)
    assert result.best_offset_hours == 24
    assert result.uplift_best == pytest.approx(0.50 - 0.10)


def test_score_uplift_now_is_zero_offset_only(monkeypatch: pytest.MonkeyPatch) -> None:
    offsets = [0, 6, 24, 72]
    control_model = _FakeModel([0.20])
    treated_model = _FakeModel([0.10, 0.05, 0.05, 0.05])

    monkeypatch.setattr(scorer, "_load_models", lambda: (control_model, treated_model))
    monkeypatch.setattr(scorer, "load_config", lambda: {"retry_offsets_hours": offsets})

    result = scorer.score(_ATTEMPT)

    assert result.best_offset_hours == 0
    assert result.uplift_now == result.uplift_best

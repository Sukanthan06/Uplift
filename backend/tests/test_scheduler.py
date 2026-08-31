from datetime import UTC, datetime

from app.services.scheduler import schedule
from app.services.scorer import UpliftScore

_NOW = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


def test_no_retry_when_uplift_best_not_positive() -> None:
    decision = schedule(UpliftScore(uplift_now=-0.1, uplift_best=0.0, best_offset_hours=0), _NOW)
    assert decision.should_retry is False
    assert decision.scheduled_for is None


def test_retries_now_when_best_offset_is_zero() -> None:
    decision = schedule(UpliftScore(uplift_now=0.3, uplift_best=0.3, best_offset_hours=0), _NOW)
    assert decision.should_retry is True
    assert decision.offset_hours == 0
    assert decision.scheduled_for == _NOW


def test_retries_later_when_best_offset_is_nonzero() -> None:
    decision = schedule(UpliftScore(uplift_now=0.05, uplift_best=0.4, best_offset_hours=24), _NOW)
    assert decision.should_retry is True
    assert decision.offset_hours == 24
    assert (decision.scheduled_for - _NOW).total_seconds() == 24 * 3600

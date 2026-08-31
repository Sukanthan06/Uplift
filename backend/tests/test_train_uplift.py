from datetime import datetime, timedelta

from ml.train_uplift import TRAIN_DAYS, VAL_DAYS, LabeledAttempt, chronological_split
from simulator.generator import load_config

_CFG = load_config()
_WINDOW_START = datetime.fromisoformat(_CFG["window"]["start"].replace("Z", "+00:00"))


def _attempt_at(days_after_start: float, arm: str = "no_retry") -> LabeledAttempt:
    return LabeledAttempt(
        order_id=f"order_{days_after_start}",
        features={"amount": 100.0},
        assigned_arm=arm,
        observed_outcome=False,
        created_at=_WINDOW_START + timedelta(days=days_after_start),
    )


def test_split_is_chronological_and_exhaustive() -> None:
    days = (0, 10, TRAIN_DAYS - 1, TRAIN_DAYS, TRAIN_DAYS + VAL_DAYS, 89)
    attempts = [_attempt_at(d) for d in days]
    train, val, test = chronological_split(attempts, _CFG)
    assert len(train) + len(val) + len(test) == len(attempts)


def test_train_never_contains_a_later_timestamp_than_val_or_test() -> None:
    attempts = [_attempt_at(d) for d in (5, 25, 45, 65, 70, 80)]
    train, val, test = chronological_split(attempts, _CFG)
    if train and val:
        assert max(a.created_at for a in train) <= min(a.created_at for a in val)
    if val and test:
        assert max(a.created_at for a in val) <= min(a.created_at for a in test)


def test_boundaries_match_configured_day_counts() -> None:
    just_before_train_end = _attempt_at(TRAIN_DAYS - 0.001)
    at_train_end = _attempt_at(TRAIN_DAYS)
    train, val, _test = chronological_split([just_before_train_end, at_train_end], _CFG)
    assert just_before_train_end in train
    assert at_train_end in val

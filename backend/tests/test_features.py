from datetime import UTC, datetime

import pytest

from ml.features import HIDDEN_STATE_KEYS, build_features, to_dataframe

_ATTEMPT = {
    "order_id": "order_1",
    "amount": 1234.56,
    "method": "upi",
    "psp": "razorpay",
    "issuer": "HDFC Bank",
    "status": "failed",
    "error_code": "upi_technical_failure",
    "error_desc": "Technical failure at bank/UPI switch (code 05)",
    "attempt_no": 1,
    "parent_attempt_id": None,
    "created_at": datetime(2026, 1, 15, 14, 30, tzinfo=UTC),
}


def test_build_features_derives_cause_family_from_error_code() -> None:
    features = build_features(_ATTEMPT)
    assert features["cause_family"] == "technical_bank_downtime"


def test_build_features_extracts_calendar_features() -> None:
    features = build_features(_ATTEMPT)
    assert features["hour_of_day"] == 14
    assert features["day_of_week"] == datetime(2026, 1, 15).weekday()


def test_build_features_includes_offset_only_when_given() -> None:
    without_offset = build_features(_ATTEMPT)
    with_offset = build_features(_ATTEMPT, offset_hours=24)
    assert "offset_hours" not in without_offset
    assert with_offset["offset_hours"] == 24


def test_build_features_rejects_hidden_state_input() -> None:
    leaked = dict(_ATTEMPT, p_recover_unretried=0.5)
    with pytest.raises(AssertionError):
        build_features(leaked)


def test_output_never_carries_the_hidden_probability_curve() -> None:
    # cause_family is a legitimate *derived* output feature (also listed in
    # HIDDEN_STATE_KEYS as an input guard against a pre-supplied copy) --
    # what must never appear in the output is the actual hidden curve.
    features = build_features(_ATTEMPT, offset_hours=6)
    probability_curve_keys = HIDDEN_STATE_KEYS - {"cause_family", "is_transient"}
    assert not probability_curve_keys & features.keys()


def test_to_dataframe_uses_fixed_categories_not_observed_data() -> None:
    df = to_dataframe([build_features(_ATTEMPT)])
    assert "ICICI Bank" in df["issuer"].cat.categories
    assert "card_declined" in df["error_code"].cat.categories

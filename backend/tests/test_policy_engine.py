from datetime import UTC, datetime

from app.schemas.diagnosis import FailureDiagnosis
from app.services.policy_engine import decide
from app.services.scorer import UpliftScore

_NOW = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


def _diagnosis(**overrides) -> FailureDiagnosis:
    defaults = dict(
        root_cause="test",
        cause_family="technical_bank_downtime",
        is_transient=True,
        confidence=0.9,
    )
    defaults.update(overrides)
    return FailureDiagnosis(**defaults)


def test_unreconciled_status_blocks_regardless_of_uplift() -> None:
    score = UpliftScore(uplift_now=0.5, uplift_best=0.5, best_offset_hours=0)
    decision = decide(
        is_known_failed=False,
        cause_family="technical_bank_downtime",
        diagnosis=_diagnosis(),
        uplift_score=score,
        now=_NOW,
    )
    assert decision.chosen_action == "no_retry"
    assert decision.rules_fired == ["require_reconciliation"]


def test_blocked_cause_family_overrides_positive_uplift() -> None:
    score = UpliftScore(uplift_now=0.9, uplift_best=0.9, best_offset_hours=0)
    decision = decide(
        is_known_failed=True,
        cause_family="risk_fraud",
        diagnosis=_diagnosis(),
        uplift_score=score,
        now=_NOW,
    )
    assert decision.chosen_action == "no_retry"
    assert "block_cause_families" in decision.rules_fired


def test_block_uses_deterministic_cause_family_not_the_llms_opinion() -> None:
    """Regression test: a live run showed the LLM misclassify a
    card_or_account_issue attempt as customer_error. The block must fire
    off the deterministic taxonomy classification passed in, even when the
    LLM's own diagnosis.cause_family disagrees and would not be blocked."""
    score = UpliftScore(uplift_now=0.9, uplift_best=0.9, best_offset_hours=0)
    diagnosis = _diagnosis(cause_family="customer_error")  # LLM disagrees, would NOT block
    decision = decide(
        is_known_failed=True,
        cause_family="card_or_account_issue",  # deterministic taxonomy classification
        diagnosis=diagnosis,
        uplift_score=score,
        now=_NOW,
    )
    assert decision.chosen_action == "no_retry"
    assert "block_cause_families" in decision.rules_fired


def test_low_confidence_diagnosis_blocks_retry() -> None:
    score = UpliftScore(uplift_now=0.9, uplift_best=0.9, best_offset_hours=0)
    diagnosis = _diagnosis(confidence=0.1)
    decision = decide(
        is_known_failed=True,
        cause_family="technical_bank_downtime",
        diagnosis=diagnosis,
        uplift_score=score,
        now=_NOW,
    )
    assert decision.chosen_action == "no_retry"
    assert "require_diagnosis_confidence" in decision.rules_fired


def test_non_positive_uplift_blocks_retry() -> None:
    score = UpliftScore(uplift_now=0.0, uplift_best=0.0, best_offset_hours=0)
    decision = decide(
        is_known_failed=True,
        cause_family="technical_bank_downtime",
        diagnosis=_diagnosis(),
        uplift_score=score,
        now=_NOW,
    )
    assert decision.chosen_action == "no_retry"
    assert "require_positive_uplift" in decision.rules_fired


def test_all_gates_pass_retries_at_predicted_best_time() -> None:
    score = UpliftScore(uplift_now=0.1, uplift_best=0.4, best_offset_hours=24)
    decision = decide(
        is_known_failed=True,
        cause_family="technical_bank_downtime",
        diagnosis=_diagnosis(),
        uplift_score=score,
        now=_NOW,
    )
    assert decision.chosen_action == "retry"
    assert decision.rules_fired == []
    assert (decision.best_retry_time - _NOW).total_seconds() == 24 * 3600


def test_multiple_failed_gates_are_all_reported() -> None:
    score = UpliftScore(uplift_now=0.0, uplift_best=0.0, best_offset_hours=0)
    diagnosis = _diagnosis(confidence=0.1)
    decision = decide(
        is_known_failed=True,
        cause_family="risk_fraud",
        diagnosis=diagnosis,
        uplift_score=score,
        now=_NOW,
    )
    assert set(decision.rules_fired) == {
        "block_cause_families",
        "require_diagnosis_confidence",
        "require_positive_uplift",
    }

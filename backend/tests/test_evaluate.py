from ml.baselines import RetryPlan, do_nothing, retry_3x, retry_once, rule_based
from ml.evaluate import AttemptRecord, _sequential_outcome, score_policy

_CFG = {
    "patience_decay": {"per_attempt_multiplier": 0.75},
    "retry_cost_inr": 2.0,
}


def _attempt(**overrides) -> AttemptRecord:
    defaults = dict(
        order_id="order_1",
        amount=1000.0,
        cause_family="technical_bank_downtime",
        p_recover_unretried=0.05,
        p_recover_offsets={0: 0.85, 6: 0.85, 24: 0.85, 72: 0.85},
        actually_succeeded_silently=False,
    )
    defaults.update(overrides)
    return AttemptRecord(**defaults)


def test_sequential_outcome_single_probability() -> None:
    p_recovered, expected_retries = _sequential_outcome([0.4])
    assert p_recovered == 0.4
    assert expected_retries == 1.0


def test_sequential_outcome_stops_early_in_expectation() -> None:
    # second attempt only reached (in expectation) with probability (1 - p1)
    p_recovered, expected_retries = _sequential_outcome([0.5, 0.5])
    assert p_recovered == 0.5 + 0.5 * 0.5
    assert expected_retries == 1.0 + 0.5


def test_do_nothing_recovers_at_unretried_rate_with_zero_retries() -> None:
    attempts = [_attempt(amount=1000.0, p_recover_unretried=0.1)]
    score = score_policy(attempts, do_nothing, _CFG)
    assert score.recovered_inr == 100.0
    assert score.retry_count == 0.0
    assert score.cost_inr == 0.0


def test_retry_once_uses_offset_zero_probability() -> None:
    attempts = [_attempt(amount=1000.0, p_recover_offsets={0: 0.5, 6: 0.5, 24: 0.5, 72: 0.5})]
    score = score_policy(attempts, retry_once, _CFG)
    assert score.recovered_inr == 500.0
    assert score.retry_count == 1.0
    assert score.cost_inr == 2.0


def test_retry_3x_applies_patience_decay_across_offsets() -> None:
    probs = {0: 0.2, 6: 0.2, 24: 0.2, 72: 0.2}
    attempts = [_attempt(amount=1000.0, p_recover_offsets=probs)]
    score = score_policy(attempts, retry_3x, _CFG)
    p1 = 0.2
    p2 = 0.2 * 0.75
    p3 = 0.2 * 0.75**2
    expected_recovered = p1 + (1 - p1) * p2 + (1 - p1) * (1 - p2) * p3
    assert abs(score.recovered_inr - 1000.0 * expected_recovered) < 1e-9


def test_rule_based_never_retries_hard_declines() -> None:
    attempts = [_attempt(amount=1000.0, cause_family="card_or_account_issue")]
    score = score_policy(attempts, rule_based, _CFG)
    assert score.retry_count == 0.0
    assert rule_based("card_or_account_issue") == RetryPlan(())


def test_customer_contacts_only_counted_for_customer_error_family() -> None:
    probs = {0: 0.3, 6: 0.3, 24: 0.3, 72: 0.3}
    attempts = [
        _attempt(cause_family="customer_error", p_recover_offsets=probs),
        _attempt(cause_family="technical_bank_downtime", p_recover_offsets=probs),
    ]
    score = score_policy(attempts, retry_once, _CFG)
    assert score.customer_contacts == 1.0  # only the customer_error attempt


def test_double_charge_near_miss_requires_a_retry_to_actually_be_attempted() -> None:
    silent_success = _attempt(actually_succeeded_silently=True)
    no_retry_score = score_policy([silent_success], do_nothing, _CFG)
    assert no_retry_score.double_charge_near_misses == 0

    retried_score = score_policy([silent_success], retry_once, _CFG)
    assert retried_score.double_charge_near_misses == 1


def test_cost_per_inr_recovered_is_infinite_when_nothing_recovered() -> None:
    attempts = [_attempt(cause_family="card_or_account_issue", p_recover_unretried=0.0)]
    score = score_policy(attempts, do_nothing, _CFG)
    assert score.cost_per_inr_recovered == float("inf")

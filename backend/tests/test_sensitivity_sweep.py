from ml.sensitivity_sweep import (
    SWEEP_PARAMS,
    _margin,
    override_decline_rate_multiplier,
    override_outage_frequency,
    override_patience_decay,
    override_retry_cost,
    run_scenario,
    sweep_one,
)
from simulator.generator import load_config

_BASE_CFG = load_config()


def test_overrides_do_not_mutate_the_base_config() -> None:
    original_cost = _BASE_CFG["retry_cost_inr"]
    override_retry_cost(_BASE_CFG, 999.0)
    assert _BASE_CFG["retry_cost_inr"] == original_cost


def test_override_decline_rate_multiplier_scales_all_methods() -> None:
    cfg = override_decline_rate_multiplier(_BASE_CFG, 2.0)
    for method, rate in _BASE_CFG["base_decline_rate"].items():
        assert cfg["base_decline_rate"][method] == min(rate * 2.0, 0.95)


def test_override_outage_frequency_sets_nested_path() -> None:
    cfg = override_outage_frequency(_BASE_CFG, 7)
    assert cfg["outage"]["mean_days_between_outages"] == 7


def test_override_patience_decay_sets_nested_path() -> None:
    cfg = override_patience_decay(_BASE_CFG, 0.6)
    assert cfg["patience_decay"]["per_attempt_multiplier"] == 0.6


def test_run_scenario_scores_every_baseline() -> None:
    cfg = dict(_BASE_CFG, volume={"n_attempts": 2000})
    scores = run_scenario(cfg)
    for name in ("do_nothing", "retry_once", "retry_3x", "rule_based"):
        assert name in scores
        assert scores[name].recovered_inr >= 0


def test_sweep_one_returns_one_result_per_value() -> None:
    results = sweep_one("retry_cost", _BASE_CFG, n_attempts=1500)
    assert len(results) == len(SWEEP_PARAMS["retry_cost"]["values"])
    assert {r["value"] for r in results} == set(SWEEP_PARAMS["retry_cost"]["values"])


def test_margin_is_none_without_a_trained_uplift_model() -> None:
    scores = {"rule_based": run_scenario(dict(_BASE_CFG, volume={"n_attempts": 200}))["rule_based"]}
    assert _margin(scores) is None

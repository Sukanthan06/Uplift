from simulator.generator import generate, load_config
from simulator.taxonomy import DECLINE_TAXONOMY

_VALID_CODES = {(c.code, c.method) for c in DECLINE_TAXONOMY}
_HIDDEN_KEYS = {"p_recover_unretried", "p_recover_offsets", "cause_family", "is_transient"}


def _small_config() -> dict:
    cfg = load_config()
    cfg["volume"] = {"n_attempts": 500}
    return cfg


def test_generates_requested_count() -> None:
    rows = generate(_small_config())
    assert len(rows) == 500


def test_all_rows_are_root_attempts() -> None:
    rows = generate(_small_config())
    for row in rows:
        assert row.payment_attempt["attempt_no"] == 1
        assert row.payment_attempt["parent_attempt_id"] is None


def test_failed_rows_have_valid_decline_code_and_ground_truth() -> None:
    rows = generate(_small_config())
    failed = [r for r in rows if r.payment_attempt["status"] == "failed"]
    assert failed, "expected at least one failed attempt in 500 draws"
    for row in failed:
        method = row.payment_attempt["method"]
        code = row.payment_attempt["error_code"]
        assert (code, method) in _VALID_CODES
        assert row.ground_truth is not None
        assert 0.0 <= row.ground_truth["p_recover_unretried"] <= 1.0
        assert set(row.ground_truth["p_recover_offsets"]) == {0, 6, 24, 72}


def test_successful_rows_have_no_decline_code_or_ground_truth() -> None:
    rows = generate(_small_config())
    succeeded = [r for r in rows if r.payment_attempt["status"] == "success"]
    assert succeeded, "expected at least one successful attempt in 500 draws"
    for row in succeeded:
        assert row.payment_attempt["error_code"] is None
        assert row.ground_truth is None


def test_payment_attempt_rows_never_carry_hidden_state_keys() -> None:
    rows = generate(_small_config())
    for row in rows:
        assert not _HIDDEN_KEYS & row.payment_attempt.keys()


def test_generation_is_reproducible_given_same_seed() -> None:
    cfg = _small_config()
    rows_a = generate(cfg)
    rows_b = generate(cfg)
    assert [r.payment_attempt for r in rows_a] == [r.payment_attempt for r in rows_b]

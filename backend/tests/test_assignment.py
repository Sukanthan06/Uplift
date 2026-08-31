from simulator.assignment import assign_treatment


def test_assignment_is_deterministic() -> None:
    a = assign_treatment("order_abc123", 0.5)
    b = assign_treatment("order_abc123", 0.5)
    assert a == b


def test_assignment_is_roughly_balanced_at_scale() -> None:
    n = 5000
    treated = sum(
        1 for i in range(n) if assign_treatment(f"order_{i}", 0.5).assigned_treatment == "treatment"
    )
    ratio = treated / n
    assert 0.45 < ratio < 0.55


def test_assignment_respects_probability() -> None:
    n = 5000
    treated = sum(
        1 for i in range(n) if assign_treatment(f"order_{i}", 0.2).assigned_treatment == "treatment"
    )
    ratio = treated / n
    assert 0.15 < ratio < 0.25


def test_draw_is_in_unit_interval() -> None:
    for i in range(200):
        result = assign_treatment(f"order_{i}", 0.5)
        assert 0.0 <= result.draw < 1.0

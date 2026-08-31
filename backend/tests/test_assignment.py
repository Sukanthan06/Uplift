from collections import Counter

from simulator.assignment import ARMS, assign_treatment


def test_assignment_is_deterministic() -> None:
    a = assign_treatment("order_abc123")
    b = assign_treatment("order_abc123")
    assert a == b


def test_assignment_always_picks_a_known_arm() -> None:
    for i in range(500):
        result = assign_treatment(f"order_{i}")
        assert result.assigned_arm in ARMS


def test_assignment_is_roughly_uniform_across_arms_at_scale() -> None:
    n = 10000
    counts = Counter(assign_treatment(f"order_{i}").assigned_arm for i in range(n))
    expected = n / len(ARMS)
    for arm in ARMS:
        assert abs(counts[arm] - expected) / expected < 0.15


def test_draw_is_in_unit_interval() -> None:
    for i in range(200):
        result = assign_treatment(f"order_{i}")
        assert 0.0 <= result.draw < 1.0

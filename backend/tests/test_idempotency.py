from app.services.idempotency import build_idempotency_key


def test_idempotency_key_is_deterministic() -> None:
    a = build_idempotency_key("pay_1", "retry", "2026-01-01T00:00:00Z", "v1")
    b = build_idempotency_key("pay_1", "retry", "2026-01-01T00:00:00Z", "v1")
    assert a == b


def test_idempotency_key_differs_on_any_input_change() -> None:
    base = build_idempotency_key("pay_1", "retry", "2026-01-01T00:00:00Z", "v1")
    assert base != build_idempotency_key("pay_2", "retry", "2026-01-01T00:00:00Z", "v1")
    assert base != build_idempotency_key("pay_1", "retry", "2026-01-02T00:00:00Z", "v1")
    assert base != build_idempotency_key("pay_1", "retry", "2026-01-01T00:00:00Z", "v2")

from decimal import Decimal

from app.models import Action, Incident
from app.services.action_service import (
    MAX_API_RETRIES,
    ShadowGatewayClient,
    _attempt_gateway_call,
    execute_retry,
)

_AMOUNT = Decimal("100.00")


class _ScriptedClient:
    def __init__(self, statuses: list[int]) -> None:
        self._statuses = list(statuses)
        self.calls = 0

    def retry_payment(self, payment_id: str, amount: Decimal, currency: str = "INR") -> int:
        status = self._statuses[self.calls]
        self.calls += 1
        return status


def _no_sleep(seconds: float) -> None:
    pass


def test_immediate_success_makes_one_call() -> None:
    client = _ScriptedClient([200])
    attempt_no, status, outcome = _attempt_gateway_call("pay_1", _AMOUNT, "INR", client, _no_sleep)
    assert attempt_no == 1
    assert status == 200
    assert outcome == "success"
    assert client.calls == 1


def test_4xx_stops_immediately_as_failed_not_retried() -> None:
    client = _ScriptedClient([404])
    attempt_no, status, outcome = _attempt_gateway_call("pay_1", _AMOUNT, "INR", client, _no_sleep)
    assert attempt_no == 1
    assert outcome == "failed"
    assert client.calls == 1


def test_503_then_success_retries_once() -> None:
    client = _ScriptedClient([503, 200])
    attempt_no, status, outcome = _attempt_gateway_call("pay_1", _AMOUNT, "INR", client, _no_sleep)
    assert attempt_no == 2
    assert outcome == "success"
    assert client.calls == 2


def test_persistent_503_exhausts_budget_and_stops() -> None:
    client = _ScriptedClient([503, 503, 503, 200])  # 4th call should never happen
    attempt_no, status, outcome = _attempt_gateway_call("pay_1", _AMOUNT, "INR", client, _no_sleep)
    assert outcome == "retry_exhausted"
    assert client.calls == 1 + MAX_API_RETRIES
    assert status == 503


def test_backoff_is_called_between_retries_not_after_the_last_attempt() -> None:
    sleeps: list[float] = []
    client = _ScriptedClient([503, 503, 503])
    _attempt_gateway_call("pay_1", _AMOUNT, "INR", client, sleeps.append)
    assert len(sleeps) == MAX_API_RETRIES
    assert sleeps == sorted(sleeps)  # exponential backoff: non-decreasing


def test_execute_retry_persists_an_action_row(fake_session) -> None:
    client = _ScriptedClient([200])
    result = execute_retry(
        payment_id="order_1",
        decision_id=1,
        policy_version="v1",
        scheduled_time="2026-01-01T00:00:00",
        amount=_AMOUNT,
        client=client,
        sleep_fn=_no_sleep,
        session=fake_session,
    )
    assert result.outcome == "success"
    actions = fake_session.rows_of(Action)
    assert len(actions) == 1
    assert actions[0].idempotency_key == result.idempotency_key


def test_execute_retry_is_idempotent_on_repeat_call(fake_session) -> None:
    """Second call with identical (payment_id, action_type, scheduled_time,
    policy_version) must not call the gateway again -- it returns the
    already-persisted Action row instead."""
    first_client = _ScriptedClient([200])
    first = execute_retry(
        payment_id="order_1",
        decision_id=1,
        policy_version="v1",
        scheduled_time="2026-01-01T00:00:00",
        amount=_AMOUNT,
        client=first_client,
        sleep_fn=_no_sleep,
        session=fake_session,
    )

    class _BoomIfCalled:
        def retry_payment(self, payment_id: str, amount: Decimal, currency: str = "INR") -> int:
            raise AssertionError("gateway must not be called on a replayed idempotency key")

    second = execute_retry(
        payment_id="order_1",
        decision_id=1,
        policy_version="v1",
        scheduled_time="2026-01-01T00:00:00",
        amount=_AMOUNT,
        client=_BoomIfCalled(),
        sleep_fn=_no_sleep,
        session=fake_session,
    )

    assert second == first
    assert len(fake_session.rows_of(Action)) == 1


def test_execute_retry_writes_incident_on_budget_exhaustion(fake_session) -> None:
    client = _ScriptedClient([503, 503, 503])
    result = execute_retry(
        payment_id="order_2",
        decision_id=1,
        policy_version="v1",
        scheduled_time="2026-01-01T00:00:00",
        amount=_AMOUNT,
        client=client,
        sleep_fn=_no_sleep,
        session=fake_session,
    )
    assert result.outcome == "retry_exhausted"
    incidents = fake_session.rows_of(Incident)
    assert len(incidents) == 1
    assert incidents[0].payment_id == "order_2"
    assert incidents[0].attempts == 1 + MAX_API_RETRIES


def test_execute_retry_shadow_mode_calls_no_gateway_and_writes_no_incident(fake_session) -> None:
    result = execute_retry(
        payment_id="order_3",
        decision_id=1,
        policy_version="v1",
        scheduled_time="2026-01-01T00:00:00",
        amount=_AMOUNT,
        client=ShadowGatewayClient(),
        sleep_fn=_no_sleep,
        session=fake_session,
    )
    assert result.outcome == "shadow"
    assert fake_session.rows_of(Incident) == []

from decimal import Decimal

from app.services.action_service import (
    MAX_API_RETRIES,
    _attempt_gateway_call,
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

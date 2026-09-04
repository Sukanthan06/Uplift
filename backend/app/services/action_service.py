"""Action service: the only thing that talks to external APIs.

Idempotency (CLAUDE.md non-negotiable #3): idempotency_key built by
app/services/idempotency.py -- the only function allowed to build one.
Safe to call twice -- execute_retry() checks for an existing Action row
with the same key before ever calling the gateway again, and returns that
row's result instead of re-executing.

Retry budget (CLAUDE.md non-negotiable #4): max 2 API retries on 5xx with
exponential backoff, then STOP, write an Incident, and report
retry_exhausted -- an infra-level cap on the HTTP call itself, distinct
from policy_engine's business-level decision about whether to retry the
payment at all.

Three backends behind the same GatewayClient protocol, selected via
settings.action_mode:
- "mock" (default): deterministic, no external calls.
- "razorpay_test": real HTTP to Razorpay's sandbox (action_razorpay.py).
- "off": shadow mode -- logs the intended action, calls nothing.

GatewayClient stays a single, simple Protocol (retry_payment -> HTTP status
code) rather than a richer parallel ActionRequest/ActionResponse interface,
so both backends share 100% of the existing retry/backoff/persistence
logic below instead of forking into two parallel code paths for the same
concept. See docs/DECISIONS.md.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol

from app.logging import get_logger
from app.services.idempotency import build_idempotency_key

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = get_logger(__name__)

MAX_API_RETRIES = 2
BASE_BACKOFF_SECONDS = 0.5


@dataclass(frozen=True)
class ActionResult:
    idempotency_key: str
    api_attempt_no: int
    http_status: int | None
    outcome: str  # "success" | "failed" | "retry_exhausted" | "shadow"


class GatewayClient(Protocol):
    def retry_payment(
        self, payment_id: str, amount: Decimal, currency: str = "INR"
    ) -> int: ...  # returns an HTTP status code


class MockGatewayClient:
    """Default mock: always succeeds. Tests and the deliberate-503 demo
    inject a client that returns 503 a fixed number of times instead."""

    def retry_payment(self, payment_id: str, amount: Decimal, currency: str = "INR") -> int:
        return 200


class ShadowGatewayClient:
    """ACTION_MODE=off: logs what would have happened, calls nothing.
    Never enters the retry loop -- there's no HTTP status to retry on."""

    def retry_payment(self, payment_id: str, amount: Decimal, currency: str = "INR") -> int:
        raise NotImplementedError("ShadowGatewayClient never calls retry_payment directly")


def _default_client() -> GatewayClient:
    from app.config.settings import get_settings

    settings = get_settings()
    if settings.action_mode == "mock":
        return MockGatewayClient()
    if settings.action_mode == "razorpay_test":
        from app.services.action_razorpay import RazorpayGatewayClient

        return RazorpayGatewayClient(
            api_key=settings.razorpay_api_key,
            api_secret=settings.razorpay_api_secret,
            endpoint=settings.razorpay_test_endpoint,
        )
    if settings.action_mode == "off":
        return ShadowGatewayClient()
    raise ValueError(f"unknown action_mode {settings.action_mode!r}")  # pragma: no cover


def _attempt_gateway_call(
    payment_id: str,
    amount: Decimal,
    currency: str,
    client: GatewayClient,
    sleep_fn: Callable[[float], None],
) -> tuple[int, int | None, str]:
    """One full call sequence: the initial attempt plus up to
    MAX_API_RETRIES retries on 5xx, exponential backoff between them.
    Returns (api_attempt_no, http_status, outcome)."""
    status: int | None = None
    attempt_no = 0
    for attempt_no in range(1, MAX_API_RETRIES + 2):
        started = time.monotonic()
        status = client.retry_payment(payment_id, amount, currency)
        logger.info(
            "gateway_call_completed",
            payment_id=payment_id,
            attempt_no=attempt_no,
            http_status=status,
            latency_ms=round((time.monotonic() - started) * 1000, 1),
        )
        if status < 500:
            return attempt_no, status, ("success" if status < 300 else "failed")
        if attempt_no <= MAX_API_RETRIES:
            sleep_fn(BASE_BACKOFF_SECONDS * (2 ** (attempt_no - 1)))
    return attempt_no, status, "retry_exhausted"


def execute_retry(
    payment_id: str,
    decision_id: int,
    policy_version: str,
    scheduled_time: str,
    amount: Decimal = Decimal(0),
    currency: str = "INR",
    client: GatewayClient | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    session: Session | None = None,
) -> ActionResult:
    """Safe to call twice with the same (payment_id, scheduled_time,
    policy_version): the second call returns the first's persisted result
    instead of calling the gateway again. session is injectable for
    testing -- when provided, this function never touches app.db/settings
    at all, so it can run against a fake session with no DATABASE_URL
    configured."""
    from app.models import Action, Incident

    key = build_idempotency_key(payment_id, "retry", scheduled_time, policy_version)
    logger.info("execute_retry_started", payment_id=payment_id, idempotency_key=key)

    owns_session = session is None
    if owns_session:
        from app.db import SessionLocal

        session = SessionLocal()
    try:
        existing = session.query(Action).filter(Action.idempotency_key == key).first()
        if existing is not None:
            logger.info(
                "execute_retry_finished",
                payment_id=payment_id,
                idempotency_key=key,
                outcome=existing.outcome,
                replayed=True,
            )
            return ActionResult(
                idempotency_key=existing.idempotency_key,
                api_attempt_no=existing.api_attempt_no,
                http_status=existing.http_status,
                outcome=existing.outcome,
            )

        client = client or _default_client()

        if isinstance(client, ShadowGatewayClient):
            attempt_no, status, outcome = 0, None, "shadow"
        else:
            attempt_no, status, outcome = _attempt_gateway_call(
                payment_id, amount, currency, client, sleep_fn
            )

        session.add(
            Action(
                decision_id=decision_id,
                idempotency_key=key,
                api_attempt_no=attempt_no,
                http_status=status,
                outcome=outcome,
            )
        )

        if outcome == "retry_exhausted":
            session.add(
                Incident(
                    payment_id=payment_id,
                    action_type="retry",
                    attempts=attempt_no,
                    last_status=status,
                    error_summary=f"retry budget exhausted after {attempt_no} attempts, "
                    f"last HTTP status {status}",
                )
            )
            logger.error(
                "retry_budget_exhausted",
                payment_id=payment_id,
                attempts=attempt_no,
                last_status=status,
            )

        session.commit()
        logger.info(
            "execute_retry_finished",
            payment_id=payment_id,
            idempotency_key=key,
            outcome=outcome,
            replayed=False,
        )
        return ActionResult(
            idempotency_key=key, api_attempt_no=attempt_no, http_status=status, outcome=outcome
        )
    finally:
        if owns_session:
            session.close()

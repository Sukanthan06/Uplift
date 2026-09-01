"""Action service: the only thing that talks to external APIs.

Idempotency (CLAUDE.md non-negotiable #3): idempotency_key =
sha256(payment_id + action_type + scheduled_time + policy_version). Safe to
call twice -- execute_retry() checks for an existing Action row with the
same key before ever calling the gateway again, and returns that row's
result instead of re-executing.

Retry budget (CLAUDE.md non-negotiable #4): max 2 API retries on 5xx with
exponential backoff, then STOP and report retry_exhausted -- an infra-level
cap on the HTTP call itself, distinct from policy_engine's business-level
decision about whether to retry the payment at all.

The external API is mocked -- no real Razorpay call in this build.
GatewayClient is injectable so tests, and the Phase 5 demo, can force a
503 sequence deliberately.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Protocol

MAX_API_RETRIES = 2
BASE_BACKOFF_SECONDS = 0.5


def idempotency_key(
    payment_id: str, action_type: str, scheduled_time: str, policy_version: str
) -> str:
    raw = f"{payment_id}{action_type}{scheduled_time}{policy_version}"
    return hashlib.sha256(raw.encode()).hexdigest()


@dataclass(frozen=True)
class ActionResult:
    idempotency_key: str
    api_attempt_no: int
    http_status: int | None
    outcome: str  # "success" | "failed" | "retry_exhausted"


class GatewayClient(Protocol):
    def retry_payment(self, payment_id: str) -> int: ...  # returns an HTTP status code


class MockGatewayClient:
    """Default mock: always succeeds. Tests and the deliberate-503 demo
    inject a client that returns 503 a fixed number of times instead."""

    def retry_payment(self, payment_id: str) -> int:
        return 200


def _attempt_gateway_call(
    payment_id: str, client: GatewayClient, sleep_fn
) -> tuple[int, int | None, str]:
    """One full call sequence: the initial attempt plus up to
    MAX_API_RETRIES retries on 5xx, exponential backoff between them.
    Returns (api_attempt_no, http_status, outcome)."""
    status: int | None = None
    attempt_no = 0
    for attempt_no in range(1, MAX_API_RETRIES + 2):
        status = client.retry_payment(payment_id)
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
    client: GatewayClient | None = None,
    sleep_fn=time.sleep,
    session=None,
) -> ActionResult:
    from app.db import SessionLocal
    from app.models import Action

    client = client or MockGatewayClient()
    key = idempotency_key(payment_id, "retry", scheduled_time, policy_version)

    owns_session = session is None
    session = session or SessionLocal()
    try:
        existing = session.query(Action).filter(Action.idempotency_key == key).first()
        if existing is not None:
            return ActionResult(
                idempotency_key=existing.idempotency_key,
                api_attempt_no=existing.api_attempt_no,
                http_status=existing.http_status,
                outcome=existing.outcome,
            )

        attempt_no, status, outcome = _attempt_gateway_call(payment_id, client, sleep_fn)

        session.add(
            Action(
                decision_id=decision_id,
                idempotency_key=key,
                api_attempt_no=attempt_no,
                http_status=status,
                outcome=outcome,
            )
        )
        session.commit()
        return ActionResult(
            idempotency_key=key, api_attempt_no=attempt_no, http_status=status, outcome=outcome
        )
    finally:
        if owns_session:
            session.close()

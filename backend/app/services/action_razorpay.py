"""Real HTTP calls to Razorpay's sandbox API, test mode only.

Only this file (and action_service.py's MockGatewayClient) may talk to an
external payment API -- CLAUDE.md non-negotiable: the action service is the
only thing that talks to external APIs.

Our payment attempts are entirely simulated -- there is no real Razorpay
payment or order behind any of them. The only thing this client can
honestly do to prove genuine sandbox integration is exercise a real,
side-effect-free Razorpay endpoint: creating a fresh test Order tagged with
our internal payment_id as the receipt. No real money moves in test mode;
this is Razorpay's own documented way to smoke-test integration. It is a
proxy for "the gateway accepted this retry attempt," not a claim that a
real payment was captured.

Sync httpx.Client, not async -- this codebase is synchronous everywhere
else (SQLAlchemy sessions, FastAPI routes); an async-only client here would
be an inconsistent island. See docs/DECISIONS.md.
"""

from __future__ import annotations

import time
from decimal import Decimal

import httpx

from app.logging import get_logger

logger = get_logger(__name__)


class RazorpayGatewayClient:
    """Implements action_service.GatewayClient. Refuses to instantiate with
    anything but a test-mode key, so a misconfigured production key can
    never be used to place real charges through this path."""

    def __init__(self, api_key: str, api_secret: str, endpoint: str) -> None:
        """Raises ValueError if api_key is not a test-mode key (rzp_test_*)."""
        if not api_key.startswith("rzp_test_"):
            raise ValueError(
                "RazorpayGatewayClient requires a test-mode API key (rzp_test_*)."
                " Set ACTION_MODE=mock for local development."
            )
        self._client = httpx.Client(
            base_url=endpoint,
            auth=(api_key, api_secret),
            timeout=10.0,
        )

    def retry_payment(self, payment_id: str, amount: Decimal, currency: str = "INR") -> int:
        """Returns an HTTP status code -- action_service's existing
        retry/backoff loop handles 5xx retries and budget exhaustion
        unchanged, exactly as it does for the mock client."""
        amount_paise = int(amount * 100)
        started = time.monotonic()
        try:
            response = self._client.post(
                "/orders",
                json={
                    "amount": amount_paise,
                    "currency": currency,
                    "receipt": payment_id,
                    "notes": {"source": "uplift-action-service-retry"},
                },
            )
        except httpx.RequestError as exc:
            # Network-level failure (timeout, connection refused, DNS,
            # etc.) is indistinguishable from a gateway outage for retry
            # purposes -- treat it as a 5xx so the existing backoff loop
            # retries it within budget, same as a real 503 would be.
            logger.warning(
                "gateway_http_call_failed",
                payment_id=payment_id,
                latency_ms=round((time.monotonic() - started) * 1000, 1),
                exc_info=exc,
            )
            return 503
        logger.info(
            "gateway_http_call_completed",
            payment_id=payment_id,
            http_status=response.status_code,
            latency_ms=round((time.monotonic() - started) * 1000, 1),
        )
        return response.status_code

    def close(self) -> None:
        """Release the underlying HTTP connection pool."""
        self._client.close()

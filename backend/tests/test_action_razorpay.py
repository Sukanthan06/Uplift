from decimal import Decimal

import httpx
import pytest

from app.services.action_razorpay import RazorpayGatewayClient


def _client_with_transport(handler) -> RazorpayGatewayClient:
    client = RazorpayGatewayClient(
        api_key="rzp_test_fake", api_secret="fake_secret", endpoint="https://api.razorpay.com/v1"
    )
    client._client = httpx.Client(
        base_url="https://api.razorpay.com/v1",
        auth=("rzp_test_fake", "fake_secret"),
        transport=httpx.MockTransport(handler),
    )
    return client


def test_rejects_a_non_test_api_key() -> None:
    with pytest.raises(ValueError, match="test-mode API key"):
        RazorpayGatewayClient(
            api_key="rzp_live_something", api_secret="x", endpoint="https://api.razorpay.com/v1"
        )


def test_successful_order_creation_returns_200() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/orders"
        body = httpx.Response(200, json={"id": "order_fake123"})
        return body

    client = _client_with_transport(handler)
    status = client.retry_payment("pay_1", Decimal("100.00"), "INR")
    assert status == 200


def test_sends_amount_in_paise_and_receipt_as_payment_id() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"id": "order_fake123"})

    client = _client_with_transport(handler)
    client.retry_payment("pay_42", Decimal("19.99"), "INR")
    assert captured["amount"] == 1999
    assert captured["currency"] == "INR"
    assert captured["receipt"] == "pay_42"


def test_5xx_response_passes_through_status_unchanged() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    client = _client_with_transport(handler)
    status = client.retry_payment("pay_1", Decimal("100.00"), "INR")
    assert status == 503


def test_network_error_maps_to_503_for_the_existing_retry_loop() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = _client_with_transport(handler)
    status = client.retry_payment("pay_1", Decimal("100.00"), "INR")
    assert status == 503


def test_4xx_response_passes_through_status_unchanged() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"description": "bad request"}})

    client = _client_with_transport(handler)
    status = client.retry_payment("pay_1", Decimal("100.00"), "INR")
    assert status == 400

import json

import pytest

from app.services.diagnoser import MAX_LLM_RETRIES, diagnose

_ATTEMPT = {
    "method": "upi",
    "error_code": "upi_technical_failure",
    "error_desc": "Technical failure at bank/UPI switch (code 05)",
    "issuer": "HDFC Bank",
}

_VALID_RESPONSE = json.dumps(
    {
        "root_cause": "Bank switch was temporarily unreachable",
        "cause_family": "technical_bank_downtime",
        "is_transient": True,
        "confidence": 0.9,
    }
)


class _FakeClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def complete(self, prompt: str) -> str:
        self.calls += 1
        return self._responses[self.calls - 1]


def test_valid_response_parses_on_first_try() -> None:
    client = _FakeClient([_VALID_RESPONSE])
    diagnosis = diagnose(_ATTEMPT, client=client)
    assert diagnosis.cause_family == "technical_bank_downtime"
    assert diagnosis.is_transient is True
    assert client.calls == 1


def test_invalid_json_then_valid_response_retries_and_succeeds() -> None:
    client = _FakeClient(["not json at all", _VALID_RESPONSE])
    diagnosis = diagnose(_ATTEMPT, client=client)
    assert diagnosis.cause_family == "technical_bank_downtime"
    assert client.calls == 2


def test_valid_json_wrong_schema_counts_as_a_retry() -> None:
    wrong_schema = json.dumps({"foo": "bar"})
    client = _FakeClient([wrong_schema, _VALID_RESPONSE])
    diagnosis = diagnose(_ATTEMPT, client=client)
    assert diagnosis.cause_family == "technical_bank_downtime"
    assert client.calls == 2


def test_exhausting_all_retries_raises() -> None:
    client = _FakeClient(["bad"] * (1 + MAX_LLM_RETRIES))
    with pytest.raises(ValueError, match="no valid FailureDiagnosis"):
        diagnose(_ATTEMPT, client=client)
    assert client.calls == 1 + MAX_LLM_RETRIES


def test_invalid_cause_family_is_rejected() -> None:
    bad_family = json.dumps(
        {
            "root_cause": "x",
            "cause_family": "not_a_real_family",
            "is_transient": True,
            "confidence": 0.5,
        }
    )
    client = _FakeClient([bad_family, _VALID_RESPONSE])
    diagnosis = diagnose(_ATTEMPT, client=client)
    assert diagnosis.cause_family == "technical_bank_downtime"
    assert client.calls == 2


def test_confidence_out_of_range_is_rejected() -> None:
    bad_confidence = json.dumps(
        {
            "root_cause": "x",
            "cause_family": "technical_bank_downtime",
            "is_transient": True,
            "confidence": 1.5,
        }
    )
    client = _FakeClient([bad_confidence, _VALID_RESPONSE])
    diagnosis = diagnose(_ATTEMPT, client=client)
    assert diagnosis.confidence == 0.9
    assert client.calls == 2

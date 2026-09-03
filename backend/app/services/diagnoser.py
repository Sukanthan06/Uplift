"""LLM diagnoser: decline code -> structured FailureDiagnosis.

CLAUDE.md non-negotiable #1: the LLM never makes money decisions here --
it only classifies. Uses Groq, not the vendor originally specified in
CLAUDE.md's stack (see docs/DECISIONS.md for why). Structured output
is Pydantic-validated; invalid/unparseable responses are retried up to
MAX_LLM_RETRIES times before raising, per CLAUDE.md Phase 5.

The LLMClient Protocol makes the actual provider swappable and, more
importantly, testable: unit tests inject a fake client returning canned
strings, so the test suite never makes a network call.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Protocol

from groq import Groq
from pydantic import ValidationError

from app.config.settings import get_settings
from app.schemas.diagnosis import FailureDiagnosis

MAX_LLM_RETRIES = 2

_CAUSE_FAMILIES = (
    "technical_bank_downtime",
    "insufficient_funds",
    "card_or_account_issue",
    "customer_error",
    "risk_fraud",
)

_SYSTEM_PROMPT = f"""You are a payment failure classifier. Given a payment \
gateway's decline code and description, classify it into a structured \
diagnosis. You do not decide whether to retry the payment or make any \
financial judgment -- only classify the failure.

Respond with ONLY a JSON object with exactly these fields:
- root_cause: a short (<=256 char) human-readable explanation of why the \
payment likely failed
- cause_family: one of {list(_CAUSE_FAMILIES)}
- is_transient: true if retrying is likely to help (e.g. a temporary bank \
or network issue), false if it's a hard failure (e.g. expired card, fraud, \
wrong PIN)
- confidence: your confidence in this classification, from 0.0 to 1.0

No prose, no markdown fences, just the JSON object."""


class LLMClient(Protocol):
    def complete(self, prompt: str) -> str: ...


class GroqClient:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = Groq(api_key=api_key)
        self._model = model

    def complete(self, prompt: str) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content


@lru_cache(maxsize=1)
def _default_client() -> GroqClient:
    settings = get_settings()
    return GroqClient(api_key=settings.groq_api_key, model=settings.groq_model)


def _build_prompt(attempt: dict[str, Any]) -> str:
    return (
        f"Payment method: {attempt['method']}\n"
        f"Error code: {attempt['error_code']}\n"
        f"Error description: {attempt.get('error_desc') or '(none provided)'}\n"
        f"Issuer: {attempt.get('issuer') or '(none)'}\n"
    )


def diagnose(attempt: dict[str, Any], client: LLMClient | None = None) -> FailureDiagnosis:
    """attempt must carry at least method, error_code, error_desc, issuer.
    Raises ValueError after MAX_LLM_RETRIES consecutive invalid responses."""
    client = client or _default_client()
    prompt = _build_prompt(attempt)

    last_error: Exception | None = None
    for _ in range(1 + MAX_LLM_RETRIES):
        raw = client.complete(prompt)
        try:
            payload = json.loads(raw)
            return FailureDiagnosis.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = exc
            continue

    raise ValueError(
        f"diagnoser: LLM produced no valid FailureDiagnosis after {1 + MAX_LLM_RETRIES} attempts"
    ) from last_error

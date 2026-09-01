"""FailureDiagnosis: the LLM's only allowed output shape.

CLAUDE.md non-negotiable #1: the LLM never makes money decisions. It
converts a decline code (plus whatever raw gateway text is available) into
this structured object. The uplift model and policy engine decide what
happens next -- this schema is deliberately narrow so there's no path for
the LLM to smuggle a retry/no-retry decision or a monetary figure into its
output.

cause_family is constrained to the same taxonomy simulator/taxonomy.py uses
to label training data, so a diagnosis is always comparable to the
deterministic classification, not a free-form category the rest of the
system doesn't understand.
"""

from typing import Literal

from pydantic import BaseModel, Field

CauseFamily = Literal[
    "technical_bank_downtime",
    "insufficient_funds",
    "card_or_account_issue",
    "customer_error",
    "risk_fraud",
]


class FailureDiagnosis(BaseModel):
    root_cause: str = Field(
        ..., min_length=1, max_length=256, description="Short human-readable explanation"
    )
    cause_family: CauseFamily
    is_transient: bool
    confidence: float = Field(..., ge=0.0, le=1.0)

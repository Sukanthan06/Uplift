"""Decline-code taxonomy grounded in real PSP/network documentation.

Sources (see each entry's `source` field for the specific citation):
- Razorpay's own documented card error codes:
  razorpay.com/docs/errors/payments/cards/
- ISO 8583 response codes (card networks generally):
  docs.ebanx.com/docs/pay-in/dev-tools/response-codes/iso8583-codes
- NPCI UPI error/response codes as published in bank integration docs
  (e.g. Axis Bank's "UPI Response Codes for H2H/API")

Netbanking and wallet codes are not covered by a method-specific published
list found during research. Those entries reuse the same cause families as
the documented card/UPI reasons and are marked "(extrapolated)" in their
source field rather than presented as directly cited.

Per-code `weight` values are illustrative relative frequencies within a
method's failure population, not sourced statistics — real-world decline
distributions are proprietary. They exist so sim_config.yaml's sensitivity
sweep (Phase 4) has something concrete to vary.
"""

from dataclasses import dataclass

CauseFamily = str  # one of CAUSE_FAMILIES, kept as str for simplicity

CAUSE_FAMILIES: frozenset[CauseFamily] = frozenset(
    {
        "technical_bank_downtime",
        "insufficient_funds",
        "card_or_account_issue",
        "customer_error",
        "risk_fraud",
    }
)


@dataclass(frozen=True)
class DeclineCode:
    code: str
    method: str
    cause_family: CauseFamily
    is_transient: bool
    description: str
    source: str
    weight: float


_RAZORPAY_CARDS = "Razorpay Docs, Cards Error Codes (razorpay.com/docs/errors/payments/cards/)"
_ISO8583 = "ISO 8583 response codes (docs.ebanx.com/.../response-codes/iso8583-codes)"
_UPI = "NPCI UPI error/response codes per bank integration docs (e.g. Axis Bank UPI codes)"
_EXTRAPOLATED = _RAZORPAY_CARDS + " -- cross-method reasons, extrapolated"

DECLINE_TAXONOMY: tuple[DeclineCode, ...] = (
    # --- card: transient ---
    DeclineCode(
        "payment_timed_out",
        "card",
        "technical_bank_downtime",
        True,
        "Customer exceeded the payment time limit (~10 min)",
        _RAZORPAY_CARDS,
        0.08,
    ),
    DeclineCode(
        "gateway_technical_error",
        "card",
        "technical_bank_downtime",
        True,
        "Partner bank / gateway downtime",
        _RAZORPAY_CARDS,
        0.06,
    ),
    DeclineCode(
        "bank_technical_error",
        "card",
        "technical_bank_downtime",
        True,
        "Issuing bank experienced downtime",
        _RAZORPAY_CARDS,
        0.08,
    ),
    DeclineCode(
        "iso_91_issuer_inoperative",
        "card",
        "technical_bank_downtime",
        True,
        "Issuer or switch inoperative (ISO 8583 code 91)",
        _ISO8583,
        0.05,
    ),
    DeclineCode(
        "iso_96_system_malfunction",
        "card",
        "technical_bank_downtime",
        True,
        "System malfunction (ISO 8583 code 96)",
        _ISO8583,
        0.03,
    ),
    # --- card: hard / customer action ---
    DeclineCode(
        "insufficient_funds",
        "card",
        "insufficient_funds",
        False,
        "Account lacks required balance (ISO 8583 code 51)",
        _RAZORPAY_CARDS,
        0.22,
    ),
    DeclineCode(
        "card_declined",
        "card",
        "card_or_account_issue",
        False,
        "Generic issuer decline, no specifics given (ISO 8583 code 05, 'do not honor')",
        _RAZORPAY_CARDS,
        0.18,
    ),
    DeclineCode(
        "card_expired",
        "card",
        "card_or_account_issue",
        False,
        "Card has expired (ISO 8583 code 54)",
        _RAZORPAY_CARDS,
        0.06,
    ),
    DeclineCode(
        "debit_instrument_inactive",
        "card",
        "card_or_account_issue",
        False,
        "Card not activated for online use",
        _RAZORPAY_CARDS,
        0.04,
    ),
    DeclineCode(
        "debit_instrument_blocked",
        "card",
        "card_or_account_issue",
        False,
        "Card blocked by customer or issuing bank",
        _RAZORPAY_CARDS,
        0.03,
    ),
    DeclineCode(
        "authentication_failed",
        "card",
        "customer_error",
        False,
        "Incorrect OTP or browser closed during verification",
        _RAZORPAY_CARDS,
        0.10,
    ),
    DeclineCode(
        "incorrect_cvv",
        "card",
        "customer_error",
        False,
        "Wrong CVV entered",
        _RAZORPAY_CARDS,
        0.03,
    ),
    DeclineCode(
        "payment_cancelled",
        "card",
        "customer_error",
        False,
        "Customer cancelled or backed out of checkout",
        _RAZORPAY_CARDS,
        0.03,
    ),
    DeclineCode(
        "payment_risk_check_failed",
        "card",
        "risk_fraud",
        False,
        "Bank's risk engine flagged the transaction (ISO 8583 code 59, suspected fraud)",
        _RAZORPAY_CARDS,
        0.02,
    ),
    DeclineCode(
        "transaction_limit_exceeded",
        "card",
        "card_or_account_issue",
        False,
        "Daily/per-transaction limit exceeded (ISO 8583 code 61)",
        _RAZORPAY_CARDS,
        0.02,
    ),
    # --- upi: transient ---
    DeclineCode(
        "upi_technical_failure",
        "upi",
        "technical_bank_downtime",
        True,
        "Technical failure at bank/UPI switch (code 05)",
        _UPI,
        0.12,
    ),
    DeclineCode(
        "upi_timeout",
        "upi",
        "technical_bank_downtime",
        True,
        "Request timed out (code U91/091)",
        _UPI,
        0.10,
    ),
    DeclineCode(
        "upi_issuer_not_live",
        "upi",
        "technical_bank_downtime",
        True,
        "Issuer not live on UPI at time of request (code 15)",
        _UPI,
        0.05,
    ),
    # --- upi: hard / customer action ---
    DeclineCode(
        "upi_invalid_amount",
        "upi",
        "card_or_account_issue",
        False,
        "Invalid amount field (code 13)",
        _UPI,
        0.05,
    ),
    DeclineCode(
        "upi_invalid_account",
        "upi",
        "card_or_account_issue",
        False,
        "Invalid account/VPA (code 14)",
        _UPI,
        0.10,
    ),
    DeclineCode(
        "upi_pin_block_error",
        "upi",
        "customer_error",
        False,
        "UPI PIN block error (code 10)",
        _UPI,
        0.08,
    ),
    DeclineCode(
        "upi_customer_cancelled",
        "upi",
        "customer_error",
        False,
        "Customer cancelled the collect/pay request (code 17)",
        _UPI,
        0.10,
    ),
    DeclineCode(
        "upi_insufficient_funds",
        "upi",
        "insufficient_funds",
        False,
        "Account lacks required balance",
        _UPI,
        0.20,
    ),
    # --- netbanking (extrapolated) ---
    DeclineCode(
        "netbanking_bank_technical_error",
        "netbanking",
        "technical_bank_downtime",
        True,
        "Issuing bank's netbanking gateway is down",
        _EXTRAPOLATED,
        0.30,
    ),
    DeclineCode(
        "netbanking_session_timeout",
        "netbanking",
        "technical_bank_downtime",
        True,
        "Customer exceeded the netbanking session time limit",
        _EXTRAPOLATED,
        0.15,
    ),
    DeclineCode(
        "netbanking_insufficient_funds",
        "netbanking",
        "insufficient_funds",
        False,
        "Account lacks required balance",
        _EXTRAPOLATED,
        0.30,
    ),
    DeclineCode(
        "netbanking_declined",
        "netbanking",
        "card_or_account_issue",
        False,
        "Bank declined without specifics",
        _EXTRAPOLATED,
        0.25,
    ),
    # --- wallet (extrapolated) ---
    DeclineCode(
        "wallet_insufficient_balance",
        "wallet",
        "insufficient_funds",
        False,
        "Wallet balance too low",
        _EXTRAPOLATED,
        0.45,
    ),
    DeclineCode(
        "wallet_risk_check_failed",
        "wallet",
        "risk_fraud",
        False,
        "Wallet provider's risk engine flagged the transaction",
        _EXTRAPOLATED,
        0.15,
    ),
    DeclineCode(
        "wallet_technical_error",
        "wallet",
        "technical_bank_downtime",
        True,
        "Wallet provider technical/gateway error",
        _EXTRAPOLATED,
        0.40,
    ),
)

# Codes where the gateway genuinely could not confirm outcome (a timeout, not
# a definite decline) -- the classic case CLAUDE.md non-negotiable #2 exists
# for: the charge may have silently gone through despite the "failure". The
# simulator uses this set to occasionally flip such an attempt to "actually
# succeeded silently" in hidden ground truth, so evaluate.py's
# double-charge-near-miss metric measures something that actually happened,
# not a proxy. See docs/ASSUMPTIONS.md.
TIMEOUT_AMBIGUOUS_CODES: frozenset[str] = frozenset(
    {"payment_timed_out", "upi_timeout", "netbanking_session_timeout"}
)


def codes_for_method(method: str) -> tuple[DeclineCode, ...]:
    """Every DeclineCode registered for method. Raises KeyError if none are."""
    codes = tuple(c for c in DECLINE_TAXONOMY if c.method == method)
    if not codes:
        raise KeyError(f"no decline codes registered for method {method!r}")
    return codes


def get(code: str, method: str) -> DeclineCode:
    """The DeclineCode for (code, method). Raises KeyError if unregistered."""
    for c in DECLINE_TAXONOMY:
        if c.code == code and c.method == method:
            return c
    raise KeyError(f"no decline code {code!r} for method {method!r}")

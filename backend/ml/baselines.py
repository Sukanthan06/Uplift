"""Baseline retry policies, scored by ml/evaluate.py.

Each policy maps a failed attempt's cause_family to a RetryPlan: an ordered
list of retry offsets (hours) to attempt in sequence, stopping at first
success. An empty list means "never retry."

cause_family comes from a deterministic taxonomy.py lookup on error_code --
the same static classification used to label the simulated data, not
simulator hidden state (the hidden recovery-probability curve stays off
limits; see docs/ASSUMPTIONS.md).
"""

from collections.abc import Callable
from dataclasses import dataclass

RETRY_ONCE_OFFSETS = (0,)
RETRY_3X_OFFSETS = (0, 6, 24)  # first three of sim_config.yaml's four candidates


@dataclass(frozen=True)
class RetryPlan:
    offsets_hours: tuple[int, ...]


def do_nothing(cause_family: str) -> RetryPlan:
    """Never retry, regardless of cause_family."""
    return RetryPlan(())


def retry_once(cause_family: str) -> RetryPlan:
    """Retry immediately, exactly once, regardless of cause_family."""
    return RetryPlan(RETRY_ONCE_OFFSETS)


def retry_3x(cause_family: str) -> RetryPlan:
    """Retry at 0h/6h/24h regardless of cause_family."""
    return RetryPlan(RETRY_3X_OFFSETS)


def rule_based(cause_family: str) -> RetryPlan:
    """Hand-picked offsets per cause_family -- skip hard declines, time the rest."""
    if cause_family in ("card_or_account_issue", "risk_fraud"):
        return RetryPlan(())  # hard decline -- retrying wastes money
    if cause_family == "technical_bank_downtime":
        return RetryPlan((6,))  # wait out the outage
    if cause_family == "insufficient_funds":
        return RetryPlan((72,))  # payday effect
    if cause_family == "customer_error":
        return RetryPlan((24,))  # next-day nudge
    raise ValueError(f"unknown cause_family {cause_family!r}")


Policy = Callable[[str], RetryPlan]

BASELINES: dict[str, Policy] = {
    "do_nothing": do_nothing,
    "retry_once": retry_once,
    "retry_3x": retry_3x,
    "rule_based": rule_based,
}

"""Picks retry timing (now vs later) from the uplift model's score.

A pure decision function: given a scorer.UpliftScore, decide whether to
retry at all, and if so, when. The policy engine (Phase 5) gates this
against policy.yaml rules and the hard retry budget -- this module only
answers the timing question the scorer's uplift(now)/uplift(best) numbers
imply.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from app.logging import get_logger
from app.services.scorer import UpliftScore

logger = get_logger(__name__)


@dataclass(frozen=True)
class RetryDecision:
    should_retry: bool
    scheduled_for: datetime | None
    offset_hours: int | None
    reason: str


def schedule(score: UpliftScore, now: datetime) -> RetryDecision:
    """Turn an UpliftScore into a should-retry/when decision -- pure timing
    logic, not a policy gate (see policy_engine.decide() for that)."""
    if score.uplift_best <= 0:
        decision = RetryDecision(
            should_retry=False,
            scheduled_for=None,
            offset_hours=None,
            reason=f"uplift_best={score.uplift_best:.4f} <= 0, retrying would not help",
        )
    else:
        scheduled_for = now + timedelta(hours=score.best_offset_hours)
        reason = (
            "retry now, model predicts this is the best available window"
            if score.best_offset_hours == 0
            else f"retry in {score.best_offset_hours}h, model predicts that beats retrying now"
        )
        decision = RetryDecision(
            should_retry=True,
            scheduled_for=scheduled_for,
            offset_hours=score.best_offset_hours,
            reason=reason,
        )

    logger.info("schedule_decided", **asdict(decision))
    return decision

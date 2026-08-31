"""Picks retry timing (now vs later) from the uplift model's score.

A pure decision function: given a scorer.UpliftScore, decide whether to
retry at all, and if so, when. The policy engine (Phase 5) gates this
against policy.yaml rules and the hard retry budget -- this module only
answers the timing question the scorer's uplift(now)/uplift(best) numbers
imply.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.services.scorer import UpliftScore


@dataclass(frozen=True)
class RetryDecision:
    should_retry: bool
    scheduled_for: datetime | None
    offset_hours: int | None
    reason: str


def schedule(score: UpliftScore, now: datetime) -> RetryDecision:
    if score.uplift_best <= 0:
        return RetryDecision(
            should_retry=False,
            scheduled_for=None,
            offset_hours=None,
            reason=f"uplift_best={score.uplift_best:.4f} <= 0, retrying would not help",
        )
    scheduled_for = now + timedelta(hours=score.best_offset_hours)
    reason = (
        "retry now, model predicts this is the best available window"
        if score.best_offset_hours == 0
        else f"retry in {score.best_offset_hours}h, model predicts that beats retrying now"
    )
    return RetryDecision(
        should_retry=True,
        scheduled_for=scheduled_for,
        offset_hours=score.best_offset_hours,
        reason=reason,
    )

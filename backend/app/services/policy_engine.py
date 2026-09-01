"""Deterministic policy gate: reads app/config/policy.yaml and decides
whether to retry a reconciled, diagnosed payment attempt, given the uplift
model's score.

Layers deterministic business rules on top of scheduler.schedule()'s
uplift-driven timing decision -- reconciliation, cause-family blocking, and
diagnosis-confidence all gate independently of what the model predicts.

block_cause_families checks the DETERMINISTIC taxonomy.py classification
(cause_family, passed in separately), never the LLM's own diagnosis.
cause_family -- a live test caught the LLM disagreeing with the taxonomy on
a real example (classified upi_invalid_account, a card_or_account_issue
hard decline, as customer_error), which would have let a blocked retry
through if the safety gate trusted the LLM's opinion. CLAUDE.md
non-negotiable #1 says the LLM never makes money decisions; trusting its
classification for a blocking gate would be exactly that, one level
removed. See docs/DECISIONS.md (Phase 5).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import yaml

from app.schemas.diagnosis import FailureDiagnosis
from app.services.scheduler import schedule
from app.services.scorer import UpliftScore

POLICY_PATH = Path(__file__).parent.parent / "config" / "policy.yaml"


@dataclass(frozen=True)
class PolicyDecision:
    chosen_action: str  # "retry" | "no_retry"
    rules_fired: list[str]
    policy_version: str
    uplift_now: float
    uplift_best: float
    best_retry_time: datetime | None


@lru_cache(maxsize=1)
def load_policy() -> dict:
    return yaml.safe_load(POLICY_PATH.read_text())


def decide(
    is_known_failed: bool,
    cause_family: str,
    diagnosis: FailureDiagnosis,
    uplift_score: UpliftScore,
    now: datetime,
) -> PolicyDecision:
    """cause_family must be the deterministic taxonomy.py classification for
    this attempt's error_code -- not diagnosis.cause_family. diagnosis is
    still used for its confidence gate and, elsewhere, its human-readable
    root_cause."""
    policy = load_policy()
    policy_version = policy["policy_version"]
    rules_fired: list[str] = []

    def _no_retry() -> PolicyDecision:
        return PolicyDecision(
            chosen_action="no_retry",
            rules_fired=rules_fired,
            policy_version=policy_version,
            uplift_now=uplift_score.uplift_now,
            uplift_best=uplift_score.uplift_best,
            best_retry_time=None,
        )

    if not is_known_failed:
        rules_fired.append("require_reconciliation")
        return _no_retry()

    blocked_families = policy["rules"]["block_cause_families"]["families"]
    if cause_family in blocked_families:
        rules_fired.append("block_cause_families")

    min_confidence = policy["rules"]["require_diagnosis_confidence"]["min_confidence"]
    if diagnosis.confidence < min_confidence:
        rules_fired.append("require_diagnosis_confidence")

    retry_decision = schedule(uplift_score, now)
    if not retry_decision.should_retry:
        rules_fired.append("require_positive_uplift")

    if rules_fired:
        return _no_retry()

    return PolicyDecision(
        chosen_action="retry",
        rules_fired=[],
        policy_version=policy_version,
        uplift_now=uplift_score.uplift_now,
        uplift_best=uplift_score.uplift_best,
        best_retry_time=retry_decision.scheduled_for,
    )

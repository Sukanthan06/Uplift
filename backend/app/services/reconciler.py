"""Reconciler: gateway status lookup, always runs first, before any retry
decision is made. CLAUDE.md non-negotiable #2: never retry until status is
known-failed.

The gateway lookup is mocked -- there's no real Razorpay to call in this
build. The mock is not a coin flip: for timeout-type decline codes
(taxonomy.TIMEOUT_AMBIGUOUS_CODES) it consults the simulator's hidden
ground truth for whether the charge actually succeeded silently despite
being reported as failed -- exactly the ambiguity this service exists to
resolve (see docs/ASSUMPTIONS.md (d)). This is NOT the leakage ml/features.py
guards against: a real gateway API call would honestly return the same
answer for a real payment; the mock just answers from a file instead of a
network request. Nothing here feeds the uplift model.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.logging import get_logger
from simulator import taxonomy

GROUND_TRUTH_PATH = (
    Path(__file__).resolve().parents[2] / "simulator" / "output" / "ground_truth.jsonl"
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class ReconciliationResult:
    gateway_reported_status: str  # "success" | "failed"
    is_known_failed: bool


@lru_cache(maxsize=1)
def _ground_truth_by_order() -> dict[str, dict[str, Any]]:
    if not GROUND_TRUTH_PATH.exists():
        return {}
    result: dict[str, dict[str, Any]] = {}
    with GROUND_TRUTH_PATH.open() as f:
        for line in f:
            record = json.loads(line)
            result[record["order_id"]] = record
    return result


def reconcile(attempt: dict[str, Any]) -> ReconciliationResult:
    """attempt must carry order_id, error_code. Always call this before any
    retry decision -- see policy_engine.decide()."""
    order_id = attempt["order_id"]
    error_code = attempt["error_code"]
    logger.info("reconcile_started", order_id=order_id, error_code=error_code)

    if error_code not in taxonomy.TIMEOUT_AMBIGUOUS_CODES:
        result = ReconciliationResult(gateway_reported_status="failed", is_known_failed=True)
    else:
        ground_truth = _ground_truth_by_order().get(order_id)
        if ground_truth is not None and ground_truth.get("actually_succeeded_silently"):
            result = ReconciliationResult(gateway_reported_status="success", is_known_failed=False)
        else:
            result = ReconciliationResult(gateway_reported_status="failed", is_known_failed=True)

    logger.info("reconcile_finished", order_id=order_id, **asdict(result))
    return result

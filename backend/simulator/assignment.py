"""Historical treatment assignment for the simulator's labeled training data.

Randomized among 5 arms per failed attempt: no_retry (control), and retry at
each of the 4 candidate offsets (0h/6h/24h/72h) -- a genuine logged
experiment per offset, not just retry-vs-no-retry. This is what lets Phase 3
train a causal model of retry *timing*, not just retry yes/no, without the
model ever touching the simulator's hidden recovery-probability curve. See
docs/ASSUMPTIONS.md.

Computed as a deterministic hash of order_id, not drawn from RNG call order
-- every assignment is independently recomputable and auditable from its
order_id alone.
"""

import hashlib
from dataclasses import dataclass

ARMS: tuple[str, ...] = ("no_retry", "retry_0h", "retry_6h", "retry_24h", "retry_72h")


@dataclass(frozen=True)
class TreatmentAssignment:
    order_id: str
    mechanism: str
    arms: tuple[str, ...]
    draw: float
    assigned_arm: str


def _uniform_from_hash(key: str) -> float:
    digest = hashlib.sha256(key.encode()).hexdigest()
    return int(digest[:16], 16) / 0xFFFFFFFFFFFFFFFF


def assign_treatment(
    order_id: str, arms: tuple[str, ...] = ARMS, salt: str = "uplift-assignment-v2"
) -> TreatmentAssignment:
    """Deterministically hash order_id into a uniform draw and map it onto
    one of arms -- same order_id always recomputes the same assignment."""
    draw = _uniform_from_hash(f"{salt}:{order_id}")
    idx = min(int(draw * len(arms)), len(arms) - 1)
    return TreatmentAssignment(
        order_id=order_id,
        mechanism="randomized",
        arms=arms,
        draw=draw,
        assigned_arm=arms[idx],
    )

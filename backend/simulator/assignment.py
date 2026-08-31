"""Historical treatment assignment for the simulator's labeled training data.

Randomized 50/50 retry assignment (see docs/ASSUMPTIONS.md for why), computed
as a deterministic hash of the order_id rather than drawn from RNG state --
every assignment is independently recomputable from its order_id alone,
without replaying the generation sequence in order. That's what makes it
"logged": the mechanism, probability, and raw draw are reconstructable and
auditable per attempt, not just an opaque random.random() call buried in a
loop.
"""

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class TreatmentAssignment:
    order_id: str
    mechanism: str
    probability: float
    draw: float
    assigned_treatment: str  # "treatment" | "control"


def _uniform_from_hash(key: str) -> float:
    digest = hashlib.sha256(key.encode()).hexdigest()
    return int(digest[:16], 16) / 0xFFFFFFFFFFFFFFFF


def assign_treatment(
    order_id: str, probability: float, salt: str = "uplift-assignment-v1"
) -> TreatmentAssignment:
    draw = _uniform_from_hash(f"{salt}:{order_id}")
    treated = draw < probability
    return TreatmentAssignment(
        order_id=order_id,
        mechanism="randomized",
        probability=probability,
        draw=draw,
        assigned_treatment="treatment" if treated else "control",
    )

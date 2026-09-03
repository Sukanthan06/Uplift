"""The only function in this codebase allowed to build an idempotency key
(CLAUDE.md non-negotiable #3).

idempotency_key = sha256(payment_id + action_type + scheduled_time +
policy_version) -- CLAUDE.md's own formula. Kept as specified there, not
redefined here, since CLAUDE.md's non-negotiables outrank any later
extension request. See docs/DECISIONS.md.
"""

import hashlib


def build_idempotency_key(
    payment_id: str, action_type: str, scheduled_time: str, policy_version: str
) -> str:
    raw = f"{payment_id}{action_type}{scheduled_time}{policy_version}"
    return hashlib.sha256(raw.encode()).hexdigest()

"""Phase 5 demo: runs one real failed payment attempt through the full
chain -- reconciler -> diagnoser -> scorer -> policy_engine -> action_service
-- and separately demonstrates the deliberate-503 retry-exhausted path.

Not part of the production service layer; a runnable script for
docs/DEMO_SCRIPT.md's "inject 503, show retry-exhausted incident" piece.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.db import SessionLocal
from app.models import Decision, PaymentAttempt
from app.services import action_service, policy_engine, reconciler
from app.services.diagnoser import diagnose
from app.services.scorer import score
from simulator import taxonomy


def _attempt_dict(row: PaymentAttempt) -> dict:
    return {
        "order_id": row.order_id,
        "amount": row.amount,
        "method": row.method,
        "issuer": row.issuer,
        "error_code": row.error_code,
        "error_desc": row.error_desc,
        "created_at": row.created_at,
    }


def run_one(row: PaymentAttempt) -> None:
    attempt = _attempt_dict(row)
    print(f"\n=== {row.order_id} | {row.method} | {row.error_code} ===")

    recon = reconciler.reconcile(attempt)
    print(
        f"reconciler: gateway_reported_status={recon.gateway_reported_status} "
        f"is_known_failed={recon.is_known_failed}"
    )

    diagnosis = diagnose(attempt)
    deterministic_cause_family = taxonomy.get(row.error_code, row.method).cause_family
    print(
        f"diagnoser:  cause_family={diagnosis.cause_family} "
        f"(taxonomy: {deterministic_cause_family}) "
        f"is_transient={diagnosis.is_transient} confidence={diagnosis.confidence:.2f}"
    )
    print(f"            root_cause: {diagnosis.root_cause}")

    uplift_score = score(attempt)
    print(
        f"scorer:     uplift_now={uplift_score.uplift_now:.4f} "
        f"uplift_best={uplift_score.uplift_best:.4f} "
        f"best_offset_hours={uplift_score.best_offset_hours}"
    )

    now = datetime.now(UTC)
    decision = policy_engine.decide(
        recon.is_known_failed, deterministic_cause_family, diagnosis, uplift_score, now
    )
    print(f"policy:     chosen_action={decision.chosen_action} rules_fired={decision.rules_fired}")

    # Every decision is persisted -- a "no_retry" decision is as much a part
    # of the audit trail as an approved retry, and Phase 7's dashboard needs
    # to show blocked decisions, not just approved ones.
    session = SessionLocal()
    try:
        decision_row = Decision(
            payment_id=row.id,
            uplift_now=decision.uplift_now,
            uplift_best=decision.uplift_best,
            best_retry_time=decision.best_retry_time,
            chosen_action=decision.chosen_action,
            policy_version=decision.policy_version,
            rules_fired=decision.rules_fired,
        )
        session.add(decision_row)
        session.commit()
        session.refresh(decision_row)
    finally:
        session.close()

    if decision.chosen_action != "retry":
        print("no action taken -- policy declined to retry")
        return

    result = action_service.execute_retry(
        payment_id=row.order_id,
        decision_id=decision_row.id,
        policy_version=decision.policy_version,
        scheduled_time=decision.best_retry_time.isoformat(),
    )
    print(
        f"action:     outcome={result.outcome} http_status={result.http_status} "
        f"api_attempt_no={result.api_attempt_no}"
    )


class _AlwaysDownClient:
    """Deliberately simulates a gateway that never recovers -- exercises the
    retry-exhausted / incident path on demand."""

    def retry_payment(self, payment_id: str) -> int:
        return 503


def demo_retry_exhausted() -> None:
    print("\n=== deliberate 503 injection: retry budget exhaustion ===")

    session = SessionLocal()
    try:
        any_attempt = (
            session.query(PaymentAttempt).filter(PaymentAttempt.status == "failed").first()
        )
        if any_attempt is None:
            raise RuntimeError("no failed payment_attempts found -- run the simulator first")
        decision_row = Decision(
            payment_id=any_attempt.id,
            uplift_now=0.1,
            uplift_best=0.1,
            best_retry_time=datetime.now(UTC),
            chosen_action="retry",
            policy_version="v1",
            rules_fired=[],
        )
        session.add(decision_row)
        session.commit()
        session.refresh(decision_row)
        decision_id = decision_row.id
    finally:
        session.close()

    result = action_service.execute_retry(
        payment_id="demo_incident_payment",
        decision_id=decision_id,
        policy_version="v1",
        scheduled_time=datetime.now(UTC).isoformat(),
        client=_AlwaysDownClient(),
        sleep_fn=lambda seconds: None,  # instant for the demo
    )
    print(
        f"action:     outcome={result.outcome} api_attempt_no={result.api_attempt_no} "
        f"(budget was {action_service.MAX_API_RETRIES} retries -> "
        f"{1 + action_service.MAX_API_RETRIES} total attempts, all 503)"
    )
    if result.outcome == "retry_exhausted":
        print("INCIDENT: retry budget exhausted, escalating (CLAUDE.md non-negotiable #4)")


if __name__ == "__main__":
    session = SessionLocal()
    try:
        rows = (
            session.query(PaymentAttempt).filter(PaymentAttempt.status == "failed").limit(3).all()
        )
    finally:
        session.close()

    for row in rows:
        run_one(row)

    demo_retry_exhausted()

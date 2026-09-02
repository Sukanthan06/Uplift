"""Phase 5/6 demo: runs real failed payment attempts through the full
pipeline (app/services/pipeline.py), then separately demonstrates the
deliberate-503 retry-exhausted path and the tamper-and-verify audit demo.

Not part of the production service layer; a runnable script for
docs/DEMO_SCRIPT.md's "inject 503, show retry-exhausted incident" and
"tamper a row, run verify" pieces.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.db import SessionLocal
from app.models import Decision, PaymentAttempt
from app.services import action_service, audit
from app.services.pipeline import run_pipeline


def run_one(row: PaymentAttempt) -> None:
    print(f"\n=== {row.order_id} | {row.method} | {row.error_code} ===")
    result = run_pipeline(row)

    print(
        f"reconciler: gateway_reported_status={result.gateway_reported_status} "
        f"is_known_failed={result.is_known_failed}"
    )
    print(
        f"diagnoser:  cause_family={result.diagnosis_cause_family} "
        f"(taxonomy: {result.deterministic_cause_family}) "
        f"is_transient={result.is_transient} confidence={result.confidence:.2f}"
    )
    print(f"            root_cause: {result.root_cause}")
    print(
        f"scorer:     uplift_now={result.uplift_now:.4f} "
        f"uplift_best={result.uplift_best:.4f} "
        f"best_offset_hours={result.best_offset_hours}"
    )
    print(f"policy:     chosen_action={result.chosen_action} rules_fired={result.rules_fired}")

    if result.chosen_action != "retry":
        print("no action taken -- policy declined to retry")
        return

    print(f"action:     outcome={result.action_outcome} http_status={result.action_http_status}")


class _AlwaysDownClient:
    """Deliberately simulates a gateway that never recovers -- exercises the
    retry-exhausted / incident path on demand."""

    def retry_payment(self, payment_id: str, amount: Decimal, currency: str = "INR") -> int:
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
        amount = any_attempt.amount  # read while still attached to this session
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
        amount=amount,
        client=_AlwaysDownClient(),
        sleep_fn=lambda seconds: None,  # instant for the demo
    )
    print(
        f"action:     outcome={result.outcome} api_attempt_no={result.api_attempt_no} "
        f"(budget was {action_service.MAX_API_RETRIES} retries -> "
        f"{1 + action_service.MAX_API_RETRIES} total attempts, all 503)"
    )
    audit.append(
        {
            "event": "action",
            "order_id": "demo_incident_payment",
            "decision_id": decision_id,
            "idempotency_key": result.idempotency_key,
            "outcome": result.outcome,
            "api_attempt_no": result.api_attempt_no,
        }
    )
    if result.outcome == "retry_exhausted":
        print("INCIDENT: retry budget exhausted, escalating (CLAUDE.md non-negotiable #4)")


def demo_tamper_and_verify() -> None:
    """CLAUDE.md Phase 6 demo piece: tamper a row, run verify, show the
    chain broken at exactly the right record."""
    from app.models import AuditLog
    from app.services.audit import verify

    print("\n=== audit chain: verify (before tampering) ===")
    results_before = verify()
    print(f"{len(results_before)} records, all_valid={all(r.valid for r in results_before)}")

    session = SessionLocal()
    try:
        target = (
            session.query(AuditLog)
            .order_by(AuditLog.id.asc())
            .offset(len(results_before) // 2)
            .first()
        )
        print(f"\ntampering with audit_log.id={target.id} directly via SQL (no hash recompute)")
        target.payload_json = {**target.payload_json, "event": "TAMPERED_BY_DEMO"}
        session.add(target)
        session.commit()
        tampered_id = target.id
    finally:
        session.close()

    print("\n=== audit chain: verify (after tampering) ===")
    results_after = verify()
    first_invalid = next((r.id for r in results_after if not r.valid), None)
    print(f"{len(results_after)} records, all_valid={all(r.valid for r in results_after)}")
    print(f"first invalid record: id={first_invalid} (tampered record was id={tampered_id})")
    for r in results_after:
        if not r.valid:
            print(f"  id={r.id} valid=False reason={r.reason!r}")
    assert first_invalid == tampered_id, "verify() did not flag the tampered record correctly"
    print("\nconfirmed: chain verification fails starting exactly at the tampered record")


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
    demo_tamper_and_verify()

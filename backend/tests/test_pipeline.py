from datetime import UTC, datetime
from decimal import Decimal

import pytest

import app.db as db_module
from app.models import Action, Decision, Diagnosis, PaymentAttempt, Reconciliation
from app.schemas.diagnosis import FailureDiagnosis
from app.services import action_service, policy_engine, reconciler
from app.services import pipeline as pipeline_module
from app.services.action_service import ActionResult
from app.services.policy_engine import PolicyDecision
from app.services.reconciler import ReconciliationResult
from app.services.scorer import UpliftScore

_ROW = PaymentAttempt(
    id=1,
    order_id="order_pipeline_1",
    customer_id="cust_1",
    amount=Decimal("500.00"),
    method="upi",
    psp="razorpay",
    issuer="HDFC Bank",
    status="failed",
    error_code="upi_technical_failure",
    error_desc="Technical failure at bank/UPI switch",
    attempt_no=1,
    created_at=datetime(2026, 1, 15, 12, 0, tzinfo=UTC),
)

_DIAGNOSIS = FailureDiagnosis(
    root_cause="Bank switch was temporarily unreachable",
    cause_family="technical_bank_downtime",
    is_transient=True,
    confidence=0.9,
)


def _patch_pipeline_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    fake_session,
    audit_calls: list[dict],
    chosen_action: str = "retry",
) -> None:
    monkeypatch.setattr(
        reconciler, "reconcile", lambda attempt: ReconciliationResult("failed", True)
    )
    monkeypatch.setattr(pipeline_module, "diagnose_attempt", lambda attempt: _DIAGNOSIS)
    monkeypatch.setattr(
        pipeline_module,
        "score_attempt",
        lambda attempt: UpliftScore(uplift_now=0.2, uplift_best=0.3, best_offset_hours=6),
    )
    monkeypatch.setattr(
        policy_engine,
        "decide",
        lambda is_known_failed, cause_family, diagnosis, uplift_score, now: PolicyDecision(
            chosen_action=chosen_action,
            rules_fired=[] if chosen_action == "retry" else ["require_positive_uplift"],
            policy_version="v1",
            uplift_now=0.2,
            uplift_best=0.3,
            best_retry_time=datetime(2026, 1, 15, 18, 0, tzinfo=UTC),
        ),
    )
    monkeypatch.setattr(
        action_service,
        "execute_retry",
        lambda **kwargs: ActionResult(
            idempotency_key="fake_key", api_attempt_no=1, http_status=200, outcome="success"
        ),
    )
    monkeypatch.setattr(
        pipeline_module.audit, "append", lambda payload: audit_calls.append(payload)
    )
    monkeypatch.setattr(db_module, "SessionLocal", lambda: fake_session)


def test_run_pipeline_persists_a_row_at_every_stage(monkeypatch, fake_session) -> None:
    audit_calls: list[dict] = []
    _patch_pipeline_dependencies(monkeypatch, fake_session, audit_calls, chosen_action="retry")

    result = pipeline_module.run_pipeline(_ROW)

    assert len(fake_session.rows_of(Reconciliation)) == 1
    assert len(fake_session.rows_of(Diagnosis)) == 1
    assert len(fake_session.rows_of(Decision)) == 1
    assert result.chosen_action == "retry"
    assert result.action_outcome == "success"
    assert result.deterministic_cause_family == "technical_bank_downtime"
    assert [c["event"] for c in audit_calls] == [
        "reconciliation",
        "diagnosis",
        "decision",
        "action",
    ]


def test_run_pipeline_skips_action_when_policy_blocks_retry(monkeypatch, fake_session) -> None:
    audit_calls: list[dict] = []
    _patch_pipeline_dependencies(monkeypatch, fake_session, audit_calls, chosen_action="no_retry")

    result = pipeline_module.run_pipeline(_ROW)

    assert result.chosen_action == "no_retry"
    assert result.action_outcome is None
    assert fake_session.rows_of(Action) == []
    assert [c["event"] for c in audit_calls] == ["reconciliation", "diagnosis", "decision"]

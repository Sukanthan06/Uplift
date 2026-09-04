"""Reusable orchestration: reconciler -> diagnoser -> scorer ->
policy_engine -> action_service, persisting a row in every relevant table
(reconciliations, diagnoses, decisions, actions) plus an audit_log entry at
every stage. Used by both app/demo_pipeline.py and the Phase 7 dashboard
API (app/api/batch.py) -- one implementation, not duplicated logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.logging import get_logger
from app.models import Decision, Diagnosis, PaymentAttempt, Reconciliation
from app.services import action_service, audit, policy_engine, reconciler
from app.services.diagnoser import diagnose as diagnose_attempt
from app.services.scorer import score as score_attempt
from simulator import taxonomy

logger = get_logger(__name__)


@dataclass(frozen=True)
class PipelineResult:
    order_id: str
    method: str
    error_code: str
    amount: float
    gateway_reported_status: str
    is_known_failed: bool
    diagnosis_cause_family: str
    deterministic_cause_family: str
    is_transient: bool
    confidence: float
    root_cause: str
    uplift_now: float
    uplift_best: float
    best_offset_hours: int
    chosen_action: str
    rules_fired: list[str]
    decision_id: int
    action_outcome: str | None
    action_http_status: int | None


def _attempt_dict(row: PaymentAttempt) -> dict[str, Any]:
    return {
        "order_id": row.order_id,
        "amount": row.amount,
        "method": row.method,
        "issuer": row.issuer,
        "error_code": row.error_code,
        "error_desc": row.error_desc,
        "created_at": row.created_at,
    }


def run_pipeline(row: PaymentAttempt) -> PipelineResult:
    """Run one failed payment attempt through the full reconciler ->
    diagnoser -> scorer -> policy_engine -> action_service chain,
    persisting a row at every stage plus an audit_log entry each time."""
    attempt = _attempt_dict(row)
    logger.info("pipeline_started", order_id=row.order_id, error_code=row.error_code)
    try:
        result = _run_pipeline_stages(row, attempt)
    except Exception:
        logger.error("pipeline_failed", order_id=row.order_id, exc_info=True)
        raise
    logger.info(
        "pipeline_finished",
        order_id=row.order_id,
        chosen_action=result.chosen_action,
        action_outcome=result.action_outcome,
    )
    return result


def _run_pipeline_stages(row: PaymentAttempt, attempt: dict[str, Any]) -> PipelineResult:
    from app.db import SessionLocal

    recon = reconciler.reconcile(attempt)
    session = SessionLocal()
    try:
        session.add(
            Reconciliation(payment_id=row.id, gateway_reported_status=recon.gateway_reported_status)
        )
        session.commit()
    finally:
        session.close()
    audit.append(
        {
            "event": "reconciliation",
            "order_id": row.order_id,
            "gateway_reported_status": recon.gateway_reported_status,
            "is_known_failed": recon.is_known_failed,
        }
    )

    diagnosis = diagnose_attempt(attempt)
    deterministic_cause_family = taxonomy.get(row.error_code, row.method).cause_family
    session = SessionLocal()
    try:
        session.add(
            Diagnosis(
                payment_id=row.id,
                root_cause=diagnosis.root_cause,
                cause_family=diagnosis.cause_family,
                is_transient=diagnosis.is_transient,
                confidence=diagnosis.confidence,
                raw_llm_response=diagnosis.model_dump(),
            )
        )
        session.commit()
    finally:
        session.close()
    audit.append(
        {
            "event": "diagnosis",
            "order_id": row.order_id,
            "root_cause": diagnosis.root_cause,
            "cause_family": diagnosis.cause_family,
            "is_transient": diagnosis.is_transient,
            "confidence": diagnosis.confidence,
        }
    )

    uplift_score = score_attempt(attempt)

    now = datetime.now(UTC)
    decision = policy_engine.decide(
        recon.is_known_failed, deterministic_cause_family, diagnosis, uplift_score, now
    )

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
    audit.append(
        {
            "event": "decision",
            "order_id": row.order_id,
            "decision_id": decision_row.id,
            "chosen_action": decision.chosen_action,
            "rules_fired": decision.rules_fired,
            "uplift_now": decision.uplift_now,
            "uplift_best": decision.uplift_best,
        }
    )

    action_outcome = None
    action_http_status = None
    if decision.chosen_action == "retry":
        result = action_service.execute_retry(
            payment_id=row.order_id,
            decision_id=decision_row.id,
            policy_version=decision.policy_version,
            scheduled_time=decision.best_retry_time.isoformat(),
            amount=row.amount,
        )
        action_outcome = result.outcome
        action_http_status = result.http_status
        audit.append(
            {
                "event": "action",
                "order_id": row.order_id,
                "decision_id": decision_row.id,
                "idempotency_key": result.idempotency_key,
                "outcome": result.outcome,
                "http_status": result.http_status,
                "api_attempt_no": result.api_attempt_no,
            }
        )

    return PipelineResult(
        order_id=row.order_id,
        method=row.method,
        error_code=row.error_code,
        amount=float(row.amount),
        gateway_reported_status=recon.gateway_reported_status,
        is_known_failed=recon.is_known_failed,
        diagnosis_cause_family=diagnosis.cause_family,
        deterministic_cause_family=deterministic_cause_family,
        is_transient=diagnosis.is_transient,
        confidence=diagnosis.confidence,
        root_cause=diagnosis.root_cause,
        uplift_now=uplift_score.uplift_now,
        uplift_best=uplift_score.uplift_best,
        best_offset_hours=uplift_score.best_offset_hours,
        chosen_action=decision.chosen_action,
        rules_fired=decision.rules_fired,
        decision_id=decision_row.id,
        action_outcome=action_outcome,
        action_http_status=action_http_status,
    )

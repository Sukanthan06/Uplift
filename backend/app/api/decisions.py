"""Thin route handler for the dashboard's Decision Detail page: per-payment
diagnosis + uplift + decision + action + audit trail, per CLAUDE.md's page
spec."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/decisions", tags=["decisions"])


class DecisionSummary(BaseModel):
    decision_id: int
    order_id: str
    method: str
    error_code: str
    amount: float
    chosen_action: str
    rules_fired: list[str]
    uplift_best: float
    created_at: datetime


class ReconciliationOut(BaseModel):
    gateway_reported_status: str
    reconciled_at: datetime


class DiagnosisOut(BaseModel):
    root_cause: str
    cause_family: str
    is_transient: bool
    confidence: float
    created_at: datetime


class ActionOut(BaseModel):
    idempotency_key: str
    api_attempt_no: int
    http_status: int | None
    outcome: str
    created_at: datetime


class AuditEventOut(BaseModel):
    id: int
    payload_json: dict
    created_at: datetime


class DecisionDetail(BaseModel):
    decision_id: int
    order_id: str
    method: str
    error_code: str
    error_desc: str | None
    amount: float
    uplift_now: float
    uplift_best: float
    best_retry_time: datetime | None
    chosen_action: str
    policy_version: str
    rules_fired: list[str]
    reconciliation: ReconciliationOut | None
    diagnosis: DiagnosisOut | None
    action: ActionOut | None
    audit_trail: list[AuditEventOut]


@router.get("", response_model=list[DecisionSummary])
def list_decisions(limit: int = 50) -> list[DecisionSummary]:
    from app.db import SessionLocal
    from app.models import Decision, PaymentAttempt

    session = SessionLocal()
    try:
        rows = (
            session.query(Decision, PaymentAttempt)
            .join(PaymentAttempt, Decision.payment_id == PaymentAttempt.id)
            .order_by(Decision.id.desc())
            .limit(limit)
            .all()
        )
        return [
            DecisionSummary(
                decision_id=decision.id,
                order_id=attempt.order_id,
                method=attempt.method,
                error_code=attempt.error_code,
                amount=float(attempt.amount),
                chosen_action=decision.chosen_action,
                rules_fired=decision.rules_fired,
                uplift_best=decision.uplift_best,
                created_at=decision.created_at,
            )
            for decision, attempt in rows
        ]
    finally:
        session.close()


@router.get("/{decision_id}", response_model=DecisionDetail)
def get_decision(decision_id: int) -> DecisionDetail:
    from app.db import SessionLocal
    from app.models import Action, Decision, Diagnosis, PaymentAttempt, Reconciliation

    session = SessionLocal()
    try:
        decision = session.get(Decision, decision_id)
        if decision is None:
            raise HTTPException(status_code=404, detail="decision not found")
        attempt = session.get(PaymentAttempt, decision.payment_id)

        reconciliation_row = (
            session.query(Reconciliation)
            .filter(Reconciliation.payment_id == decision.payment_id)
            .order_by(Reconciliation.id.desc())
            .first()
        )
        diagnosis_row = (
            session.query(Diagnosis)
            .filter(Diagnosis.payment_id == decision.payment_id)
            .order_by(Diagnosis.id.desc())
            .first()
        )
        action_row = (
            session.query(Action)
            .filter(Action.decision_id == decision.id)
            .order_by(Action.id.desc())
            .first()
        )

        from app.models import AuditLog

        audit_rows = (
            session.query(AuditLog)
            .filter(AuditLog.payload_json["order_id"].astext == attempt.order_id)
            .order_by(AuditLog.id.asc())
            .all()
        )

        return DecisionDetail(
            decision_id=decision.id,
            order_id=attempt.order_id,
            method=attempt.method,
            error_code=attempt.error_code,
            error_desc=attempt.error_desc,
            amount=float(attempt.amount),
            uplift_now=decision.uplift_now,
            uplift_best=decision.uplift_best,
            best_retry_time=decision.best_retry_time,
            chosen_action=decision.chosen_action,
            policy_version=decision.policy_version,
            rules_fired=decision.rules_fired,
            reconciliation=(
                ReconciliationOut(
                    gateway_reported_status=reconciliation_row.gateway_reported_status,
                    reconciled_at=reconciliation_row.reconciled_at,
                )
                if reconciliation_row
                else None
            ),
            diagnosis=(
                DiagnosisOut(
                    root_cause=diagnosis_row.root_cause,
                    cause_family=diagnosis_row.cause_family,
                    is_transient=diagnosis_row.is_transient,
                    confidence=diagnosis_row.confidence,
                    created_at=diagnosis_row.created_at,
                )
                if diagnosis_row
                else None
            ),
            action=(
                ActionOut(
                    idempotency_key=action_row.idempotency_key,
                    api_attempt_no=action_row.api_attempt_no,
                    http_status=action_row.http_status,
                    outcome=action_row.outcome,
                    created_at=action_row.created_at,
                )
                if action_row
                else None
            ),
            audit_trail=[
                AuditEventOut(id=r.id, payload_json=r.payload_json, created_at=r.created_at)
                for r in audit_rows
            ],
        )
    finally:
        session.close()

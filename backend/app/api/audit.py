"""Thin route handler -- all logic lives in app/services/audit.py."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.services.audit import AuditRecordResult, verify

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditVerifyRecord(BaseModel):
    id: int
    valid: bool
    reason: str | None
    event: str | None
    order_id: str | None
    hash: str


class AuditVerifyResponse(BaseModel):
    total_records: int
    all_valid: bool
    first_invalid_id: int | None
    records: list[AuditVerifyRecord]


def _to_response(results: list[AuditRecordResult]) -> AuditVerifyResponse:
    first_invalid = next((r.id for r in results if not r.valid), None)
    return AuditVerifyResponse(
        total_records=len(results),
        all_valid=all(r.valid for r in results),
        first_invalid_id=first_invalid,
        records=[
            AuditVerifyRecord(
                id=r.id,
                valid=r.valid,
                reason=r.reason,
                event=r.event,
                order_id=r.order_id,
                hash=r.hash,
            )
            for r in results
        ],
    )


@router.get("/verify", response_model=AuditVerifyResponse)
def audit_verify() -> AuditVerifyResponse:
    return _to_response(verify())

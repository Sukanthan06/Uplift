"""Hash-chained, tamper-EVIDENT audit log (CLAUDE.md non-negotiable #5).

Never call this "immutable" -- Postgres rows aren't; anyone with DB access
can UPDATE a row. What this provides is tamper-evidence: mutating any
record's payload after the fact breaks the hash chain from that record
forward, and verify() walks the whole chain to say exactly where.

Each record's hash = sha256(prev_hash + canonical_json(payload)), and the
next record's prev_hash is exactly the previous record's stored hash. A
naive tamper (edit payload_json, leave hash/prev_hash alone) is caught
immediately at that record, because its stored hash no longer matches the
recomputed one. A tamper that also recomputes that record's own hash to
hide the edit is still caught at the NEXT record, whose prev_hash no
longer matches the (now different) recomputed hash -- covering up a tamper
requires re-deriving the entire chain from that point forward, not just
one row.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.logging import get_logger

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.models import AuditLog

GENESIS_PREV_HASH = "0" * 64

logger = get_logger(__name__)


def _canonical_json(payload: dict[str, Any]) -> str:
    """Keys always sorted, regardless of how Postgres's JSONB column
    reorders them internally -- write time and verify time must produce
    identical bytes for identical logical content, or storage round-tripping
    alone would look like tampering."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _compute_hash(prev_hash: str, payload: dict[str, Any]) -> str:
    raw = prev_hash + _canonical_json(payload)
    return hashlib.sha256(raw.encode()).hexdigest()


@dataclass(frozen=True)
class AuditRecord:
    id: int
    payload_json: dict[str, Any]
    prev_hash: str | None
    hash: str


@dataclass(frozen=True)
class AuditRecordResult:
    id: int
    valid: bool
    reason: str | None  # None when valid
    event: str | None = None  # payload_json's own "event" field, for display
    order_id: str | None = None
    hash: str = ""


def verify_chain(records: list[AuditRecord]) -> list[AuditRecordResult]:
    """The actual chain-walking logic, independent of DB access -- takes
    plain records in, so it's testable without a live Postgres connection.
    Once any record fails (payload doesn't match its stored hash, or its
    prev_hash doesn't match the previous record's actual stored hash), that
    record AND every record after it are reported invalid -- regardless of
    whether a later record's own local hash math still checks out, because
    it's chained off a history that's no longer trustworthy."""
    results: list[AuditRecordResult] = []
    expected_prev_hash = GENESIS_PREV_HASH
    chain_ok = True

    for record in records:
        stored_prev_hash = record.prev_hash or GENESIS_PREV_HASH
        recomputed_hash = _compute_hash(stored_prev_hash, record.payload_json)

        link_ok = stored_prev_hash == expected_prev_hash
        hash_ok = recomputed_hash == record.hash

        reason = None
        if not hash_ok:
            chain_ok = False
            reason = "payload does not match this record's stored hash"
        elif not link_ok:
            chain_ok = False
            reason = "prev_hash does not match the previous record's stored hash"
        elif not chain_ok:
            reason = "chain already broken at an earlier record"

        results.append(
            AuditRecordResult(
                id=record.id,
                valid=chain_ok,
                reason=reason,
                event=record.payload_json.get("event"),
                order_id=record.payload_json.get("order_id"),
                hash=record.hash,
            )
        )
        expected_prev_hash = record.hash

    return results


def append(payload: dict[str, Any], session: Session | None = None) -> AuditLog:
    """Not safe for concurrent writers -- single-process/demo assumption,
    see docs/DECISIONS.md. A real deployment would need a DB-level lock or
    serializable transaction around the read-last/compute-hash/insert
    sequence to avoid two concurrent appends both chaining off the same
    prior record. session is injectable for testing -- when provided,
    this function never touches app.db/settings at all."""
    from app.models import AuditLog

    owns_session = session is None
    if owns_session:
        from app.db import SessionLocal

        session = SessionLocal()
    try:
        last = session.query(AuditLog).order_by(AuditLog.id.desc()).first()
        prev_hash = last.hash if last is not None else GENESIS_PREV_HASH
        new_hash = _compute_hash(prev_hash, payload)

        row = AuditLog(payload_json=payload, prev_hash=prev_hash, hash=new_hash)
        session.add(row)
        session.commit()
        session.refresh(row)
        logger.info("audit_append_finished", audit_event=payload.get("event"), record_id=row.id)
        return row
    finally:
        if owns_session:
            session.close()


def verify(session: Session | None = None) -> list[AuditRecordResult]:
    """Walk the whole chain from Postgres and report which records are
    valid -- see verify_chain() for the actual tamper-detection logic."""
    from app.models import AuditLog

    owns_session = session is None
    if owns_session:
        from app.db import SessionLocal

        session = SessionLocal()
    try:
        rows = session.query(AuditLog).order_by(AuditLog.id.asc()).all()
        records = [
            AuditRecord(id=r.id, payload_json=r.payload_json, prev_hash=r.prev_hash, hash=r.hash)
            for r in rows
        ]
        results = verify_chain(records)
        all_valid = all(r.valid for r in results)
        logger.info(
            "audit_verify_finished",
            total_records=len(results),
            all_valid=all_valid,
            first_invalid_id=next((r.id for r in results if not r.valid), None),
        )
        return results
    finally:
        if owns_session:
            session.close()

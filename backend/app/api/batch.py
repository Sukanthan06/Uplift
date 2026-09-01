"""Thin route handler: the Batch Run dashboard page needs live streaming of
a batch of attempts through the real pipeline (real Groq calls, real
Postgres writes) -- Server-Sent Events, one JSON event per attempt as it
completes.
"""

from __future__ import annotations

import json
from collections.abc import Generator

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/batch", tags=["batch"])


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _stream_batch(limit: int) -> Generator[str, None, None]:
    from app.db import SessionLocal
    from app.models import PaymentAttempt
    from app.services.pipeline import run_pipeline

    session = SessionLocal()
    try:
        rows = (
            session.query(PaymentAttempt)
            .filter(PaymentAttempt.status == "failed")
            .order_by(PaymentAttempt.id.asc())
            .limit(limit)
            .all()
        )
    finally:
        session.close()

    yield _sse("start", {"total": len(rows)})

    for i, row in enumerate(rows, start=1):
        try:
            result = run_pipeline(row)
            yield _sse(
                "attempt",
                {
                    "index": i,
                    "order_id": result.order_id,
                    "method": result.method,
                    "error_code": result.error_code,
                    "cause_family": result.diagnosis_cause_family,
                    "chosen_action": result.chosen_action,
                    "rules_fired": result.rules_fired,
                    "uplift_best": result.uplift_best,
                    "action_outcome": result.action_outcome,
                },
            )
        except Exception as exc:  # stream the failure to the client, don't kill the whole batch
            yield _sse("error", {"index": i, "order_id": row.order_id, "error": str(exc)})

    yield _sse("done", {"total": len(rows)})


@router.get("/run")
def batch_run(limit: int = Query(default=5, ge=1, le=50)) -> StreamingResponse:
    return StreamingResponse(_stream_batch(limit), media_type="text/event-stream")

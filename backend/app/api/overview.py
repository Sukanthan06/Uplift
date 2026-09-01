"""Thin route handler -- headline metrics for the dashboard's Overview page.

Phase 2 baselines and Phase 3 model comparison are computed from the
existing ml/evaluate.py building blocks (same methodology, nothing
reimplemented). Phase 4 sensitivity results are read from the JSON file
ml/sensitivity_sweep.py writes -- re-running that multi-minute sweep on
every page load isn't reasonable. Pipeline activity is a live DB query
against whatever app/services/pipeline.py has actually persisted.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from ml.baselines import BASELINES
from ml.evaluate import (
    load_attempts,
    load_models,
    qini_curve,
    score_policy,
    score_uplift_policy,
    test_split,
    uplift_at_k,
)
from simulator.generator import load_config

router = APIRouter(tags=["overview"])

SENSITIVITY_RESULTS_PATH = (
    Path(__file__).resolve().parents[2] / "ml" / "output" / "sensitivity" / "results.json"
)


class PolicyScoreOut(BaseModel):
    recovered_inr: float
    retry_count: float
    cost_inr: float
    cost_per_inr_recovered: float
    customer_contacts: float
    double_charge_near_misses: int


class SimulatorStats(BaseModel):
    total_attempts: int
    failed_attempts: int
    method_mix: dict[str, int]


class PipelineActivity(BaseModel):
    decisions_by_action: dict[str, int]
    actions_by_outcome: dict[str, int]
    audit_records: int
    audit_all_valid: bool


class Phase3Result(BaseModel):
    n_test: int
    baselines: dict[str, PolicyScoreOut]
    uplift_at_20pct: float
    qini_curve: list[list[float]]


class OverviewResponse(BaseModel):
    simulator: SimulatorStats
    phase2_baselines: dict[str, PolicyScoreOut]
    phase3: Phase3Result | None
    phase4_sweeps: dict | None
    pipeline_activity: PipelineActivity


def _to_score_out(score) -> PolicyScoreOut:
    return PolicyScoreOut(
        recovered_inr=score.recovered_inr,
        retry_count=score.retry_count,
        cost_inr=score.cost_inr,
        cost_per_inr_recovered=score.cost_per_inr_recovered,
        customer_contacts=score.customer_contacts,
        double_charge_near_misses=score.double_charge_near_misses,
    )


def _simulator_stats(session) -> SimulatorStats:
    from app.models import PaymentAttempt

    total = session.query(PaymentAttempt).count()
    failed = session.query(PaymentAttempt).filter(PaymentAttempt.status == "failed").count()
    method_rows = (
        session.query(PaymentAttempt.method, PaymentAttempt.id)
        .filter(PaymentAttempt.status == "failed")
        .all()
    )
    method_mix: dict[str, int] = {}
    for method, _id in method_rows:
        method_mix[method] = method_mix.get(method, 0) + 1
    return SimulatorStats(total_attempts=total, failed_attempts=failed, method_mix=method_mix)


def _pipeline_activity(session) -> PipelineActivity:
    from app.models import Action, Decision
    from app.services.audit import verify

    decisions_by_action: dict[str, int] = {}
    for (action,) in session.query(Decision.chosen_action).all():
        decisions_by_action[action] = decisions_by_action.get(action, 0) + 1

    actions_by_outcome: dict[str, int] = {}
    for (outcome,) in session.query(Action.outcome).all():
        actions_by_outcome[outcome] = actions_by_outcome.get(outcome, 0) + 1

    audit_results = verify(session=session)
    return PipelineActivity(
        decisions_by_action=decisions_by_action,
        actions_by_outcome=actions_by_outcome,
        audit_records=len(audit_results),
        audit_all_valid=all(r.valid for r in audit_results),
    )


def _phase3_result(cfg: dict) -> Phase3Result | None:
    try:
        control_model, treated_model = load_models()
    except FileNotFoundError:
        return None

    attempts = test_split(load_attempts(), cfg)
    baselines = {name: score_policy(attempts, policy, cfg) for name, policy in BASELINES.items()}
    budget = round(baselines["rule_based"].retry_count)
    baselines["uplift_ranked"] = score_uplift_policy(
        attempts, control_model, treated_model, budget, cfg
    )
    uplift20 = uplift_at_k(attempts, control_model, treated_model, cfg, 0.2)
    qini = qini_curve(attempts, control_model, treated_model, cfg)

    return Phase3Result(
        n_test=len(attempts),
        baselines={name: _to_score_out(s) for name, s in baselines.items()},
        uplift_at_20pct=uplift20,
        qini_curve=[[k, q] for k, q in qini],
    )


def _phase4_sweeps() -> dict | None:
    if not SENSITIVITY_RESULTS_PATH.exists():
        return None
    return json.loads(SENSITIVITY_RESULTS_PATH.read_text())


@router.get("/overview", response_model=OverviewResponse)
def overview() -> OverviewResponse:
    from app.db import SessionLocal

    cfg = load_config()
    session = SessionLocal()
    try:
        simulator = _simulator_stats(session)
        activity = _pipeline_activity(session)
    finally:
        session.close()

    attempts = load_attempts()
    phase2 = {name: score_policy(attempts, policy, cfg) for name, policy in BASELINES.items()}

    return OverviewResponse(
        simulator=simulator,
        phase2_baselines={name: _to_score_out(s) for name, s in phase2.items()},
        phase3=_phase3_result(cfg),
        phase4_sweeps=_phase4_sweeps(),
        pipeline_activity=activity,
    )

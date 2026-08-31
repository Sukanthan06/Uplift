"""Phase 4: sensitivity sweep. Varies sim_config.yaml parameters CLAUDE.md
names explicitly -- base decline rate, outage frequency, retry cost,
customer patience -- and shows where the uplift-ranked policy beats the
baselines and where it doesn't. Plots go to ml/output/sensitivity/.

Runs entirely in-memory (generate -> train -> evaluate), never touching
Postgres or the production model files in ml/output/*.pkl -- a sweep must
not overwrite the models Phase 3's headline numbers depend on. Uses a
smaller n_attempts (5,000 vs the production 50,000) purely for turnaround
speed across ~20+ scenarios; same methodology as Phase 2/3 otherwise. See
docs/DECISIONS.md.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from ml.baselines import BASELINES
from ml.evaluate import AttemptRecord, PolicyScore, score_policy, score_uplift_policy
from ml.train_uplift import LabeledAttempt, _fit, chronological_split
from simulator.generator import generate, load_config

OUTPUT_DIR = Path(__file__).parent / "output" / "sensitivity"
SWEEP_N_ATTEMPTS = 5000


def _to_attempt_record(payment_attempt: dict, ground_truth: dict) -> AttemptRecord:
    return AttemptRecord(
        order_id=payment_attempt["order_id"],
        amount=float(payment_attempt["amount"]),
        method=payment_attempt["method"],
        issuer=payment_attempt["issuer"],
        error_code=payment_attempt["error_code"],
        cause_family=ground_truth["cause_family"],
        created_at=payment_attempt["created_at"],
        p_recover_unretried=ground_truth["p_recover_unretried"],
        p_recover_offsets=dict(ground_truth["p_recover_offsets"]),
        actually_succeeded_silently=ground_truth["actually_succeeded_silently"],
        assigned_arm=ground_truth["assignment"]["assigned_arm"],
        observed_outcome=ground_truth["observed_outcome"],
    )


def _to_labeled_attempt(payment_attempt: dict, ground_truth: dict) -> LabeledAttempt:
    from ml.features import build_features

    arm = ground_truth["assignment"]["assigned_arm"]
    offset = None if arm == "no_retry" else int(arm.removeprefix("retry_").removesuffix("h"))
    return LabeledAttempt(
        order_id=payment_attempt["order_id"],
        features=build_features(payment_attempt, offset_hours=offset),
        assigned_arm=arm,
        observed_outcome=ground_truth["observed_outcome"],
        created_at=payment_attempt["created_at"],
    )


def run_scenario(cfg: dict) -> dict[str, PolicyScore]:
    """generate -> train -> evaluate, fully in-memory, for one sim_config."""
    rows = generate(cfg)
    failed = [r for r in rows if r.ground_truth is not None]
    attempts = [_to_attempt_record(r.payment_attempt, r.ground_truth) for r in failed]
    labeled = [_to_labeled_attempt(r.payment_attempt, r.ground_truth) for r in failed]

    train_set, _val_set, test_set = chronological_split(labeled, cfg)
    control_train = [a for a in train_set if a.assigned_arm == "no_retry"]
    treated_train = [a for a in train_set if a.assigned_arm != "no_retry"]

    test_order_ids = {a.order_id for a in test_set}
    test_attempts = [a for a in attempts if a.order_id in test_order_ids]

    scores = {name: score_policy(test_attempts, policy, cfg) for name, policy in BASELINES.items()}

    if len(control_train) >= 20 and len(treated_train) >= 20 and test_attempts:
        control_model = _fit(control_train)
        treated_model = _fit(treated_train)
        budget = round(scores["rule_based"].retry_count)
        scores["uplift_ranked"] = score_uplift_policy(
            test_attempts, control_model, treated_model, budget, cfg
        )

    return scores


def _set_path(base_cfg: dict, path: tuple[str, ...], value: Any) -> dict:
    cfg = copy.deepcopy(base_cfg)
    node = cfg
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return cfg


def override_outage_frequency(base_cfg: dict, value: float) -> dict:
    return _set_path(base_cfg, ("outage", "mean_days_between_outages"), value)


def override_retry_cost(base_cfg: dict, value: float) -> dict:
    return _set_path(base_cfg, ("retry_cost_inr",), value)


def override_patience_decay(base_cfg: dict, value: float) -> dict:
    return _set_path(base_cfg, ("patience_decay", "per_attempt_multiplier"), value)


def override_decline_rate_multiplier(base_cfg: dict, value: float) -> dict:
    cfg = copy.deepcopy(base_cfg)
    cfg["base_decline_rate"] = {
        method: min(rate * value, 0.95) for method, rate in cfg["base_decline_rate"].items()
    }
    return cfg


SWEEP_PARAMS: dict[str, dict[str, Any]] = {
    "base_decline_rate": {
        "override": override_decline_rate_multiplier,
        "values": [0.5, 0.75, 1.0, 1.5, 2.0],
        "label": "base decline rate multiplier (1.0 = sim_config.yaml default)",
    },
    "outage_frequency": {
        "override": override_outage_frequency,
        "values": [3, 7, 14, 30, 60],
        "label": "mean days between outages (lower = more frequent downtime)",
    },
    "retry_cost": {
        "override": override_retry_cost,
        "values": [0.5, 1, 2, 5, 10, 20],
        "label": "retry cost (INR)",
    },
    "customer_patience": {
        "override": override_patience_decay,
        "values": [0.5, 0.6, 0.75, 0.85, 0.95, 1.0],
        "label": "patience decay multiplier (1.0 = no fatigue)",
    },
}


def sweep_one(param_name: str, base_cfg: dict, n_attempts: int = SWEEP_N_ATTEMPTS) -> list[dict]:
    spec = SWEEP_PARAMS[param_name]
    results = []
    for value in spec["values"]:
        cfg = spec["override"](base_cfg, value)
        cfg["volume"] = {"n_attempts": n_attempts}
        scores = run_scenario(cfg)
        results.append({"value": value, "scores": scores})
    return results


def sweep_grid(
    param_a: str, param_b: str, base_cfg: dict, n_attempts: int = SWEEP_N_ATTEMPTS
) -> list[list[dict]]:
    spec_a, spec_b = SWEEP_PARAMS[param_a], SWEEP_PARAMS[param_b]
    grid = []
    for value_a in spec_a["values"]:
        row = []
        for value_b in spec_b["values"]:
            cfg = spec_a["override"](base_cfg, value_a)
            cfg = spec_b["override"](cfg, value_b)
            cfg["volume"] = {"n_attempts": n_attempts}
            scores = run_scenario(cfg)
            row.append({"value_a": value_a, "value_b": value_b, "scores": scores})
        grid.append(row)
    return grid


def _margin(scores: dict[str, PolicyScore]) -> float | None:
    """uplift_ranked's % advantage over rule_based's recovered INR, or None
    if the model couldn't be trained for this scenario (too little data)."""
    if "uplift_ranked" not in scores or scores["rule_based"].recovered_inr == 0:
        return None
    return (
        (scores["uplift_ranked"].recovered_inr - scores["rule_based"].recovered_inr)
        / scores["rule_based"].recovered_inr
        * 100
    )


def plot_sweeps(all_results: dict[str, list[dict]]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(2, 2, figsize=(12, 9))
    for ax, (param_name, results) in zip(axes.flat, all_results.items(), strict=True):
        values = [r["value"] for r in results]
        for policy_name in (*BASELINES, "uplift_ranked"):
            ys = [
                r["scores"][policy_name].recovered_inr if policy_name in r["scores"] else None
                for r in results
            ]
            if all(y is None for y in ys):
                continue
            ax.plot(values, ys, marker="o", label=policy_name)
        ax.set_xlabel(SWEEP_PARAMS[param_name]["label"], fontsize=8)
        ax.set_ylabel("recovered (INR)")
        ax.legend(fontsize=7)
    fig.suptitle("Phase 4 sensitivity sweep: recovered INR vs. sim parameter")
    fig.tight_layout()
    out_path = OUTPUT_DIR / "sensitivity_sweeps.png"
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path


def plot_heatmap(param_a: str, param_b: str, grid: list[list[dict]]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    spec_a, spec_b = SWEEP_PARAMS[param_a], SWEEP_PARAMS[param_b]
    margins = [[_margin(cell["scores"]) for cell in row] for row in grid]
    # Missing (None) cells render as 0 on the color scale, annotated "n/a".
    display = [[m if m is not None else 0.0 for m in row] for row in margins]

    known = [m for row in margins for m in row if m is not None]
    bound = max(1.0, max((abs(m) for m in known), default=1.0))

    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(display, cmap="RdYlGn", aspect="auto", vmin=-bound, vmax=bound)
    ax.set_xticks(range(len(spec_b["values"])), labels=[str(v) for v in spec_b["values"]])
    ax.set_yticks(range(len(spec_a["values"])), labels=[str(v) for v in spec_a["values"]])
    ax.set_xlabel(spec_b["label"], fontsize=8)
    ax.set_ylabel(spec_a["label"], fontsize=8)
    for i, row in enumerate(margins):
        for j, m in enumerate(row):
            text = f"{m:+.1f}%" if m is not None else "n/a"
            ax.text(j, i, text, ha="center", va="center", fontsize=8)
    fig.colorbar(im, ax=ax, label="uplift_ranked advantage over rule_based (%)")
    ax.set_title("Where the uplift-ranked policy wins vs. loses")
    fig.tight_layout()
    out_path = OUTPUT_DIR / f"heatmap_{param_a}_x_{param_b}.png"
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path


def run() -> None:
    base_cfg = load_config()

    all_results = {name: sweep_one(name, base_cfg) for name in SWEEP_PARAMS}
    sweep_path = plot_sweeps(all_results)
    print(f"sweep plot -> {sweep_path}")

    for param_name, results in all_results.items():
        print(f"\n{SWEEP_PARAMS[param_name]['label']}")
        for r in results:
            margin = _margin(r["scores"])
            margin_str = f"{margin:+.1f}%" if margin is not None else "n/a"
            print(f"  {r['value']!s:>6}  uplift_ranked vs rule_based: {margin_str}")

    # base_decline_rate x outage_frequency, not retry_cost: retry_cost only
    # affects cost_inr, never recovered_inr, so a margin defined on
    # recovered_inr is mathematically flat across it (confirmed by the 1D
    # sweep above) -- pairing it here would waste a heatmap axis.
    grid = sweep_grid("outage_frequency", "base_decline_rate", base_cfg)
    heatmap_path = plot_heatmap("outage_frequency", "base_decline_rate", grid)
    print(f"\nheatmap -> {heatmap_path}")


if __name__ == "__main__":
    run()

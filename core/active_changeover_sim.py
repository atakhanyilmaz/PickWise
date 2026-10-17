"""Active rolling-horizon changeover (setup) simulation coupled with CP-SAT scheduling.

Simulates an active workshop where a machine is currently undergoing product
changeover/setup (status=IN_PROGRESS). As time advances (t = t_0, t_1, ...),
live CNC sensor features update the ML prediction of remaining setup time
(`remaining_changeover_time_min`), which updates `remaining_duration` in the
workshop scenario and re-solves the schedule to see completion times, tardiness,
and alternative machine routing decisions.

Run with:
  python -m core.active_changeover_sim
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from pydantic import Field

from core.cpsat_solver import solve
from core.domain_rules import (
    Contract,
    DurationSource,
    JobModel,
    MachineModel,
    Nonnegative,
    OperationModel,
    OperationStatus,
    Positive,
    RouteSource,
    WorkshopScenario,
)
from core.scenarios import ScheduleResult, plan_metrics
from core.workshop_fjsp_builder import build_env

ROOT = Path(__file__).resolve().parents[1]


class ActiveStepRecord(Contract):
    step_index: Nonnegative
    current_time_min: Nonnegative
    elapsed_setup_min: float
    actual_remaining_setup_min: float
    predicted_remaining_setup_min: float
    prediction_error_min: float
    applied_remaining_duration_min: Positive
    estimated_setup_end_min: Nonnegative
    actual_setup_end_min: Nonnegative
    schedule_makespan_min: Nonnegative
    setup_job_completion_min: Nonnegative
    new_order_completion_min: Nonnegative
    late_job_count: Nonnegative
    total_tardiness_min: Nonnegative
    new_order_machine_id: Nonnegative
    alternative_machine_used: bool
    job_completions: dict[int, Nonnegative] = Field(default_factory=dict)


def build_active_changeover_scenario(
    *,
    current_time_min: int = 0,
    setup_fixed_start_min: int = 0,
    setup_remaining_min: int = 15,
    transition_label: str = "A->B",
) -> WorkshopScenario:
    """Create a workshop scenario with an active changeover/setup on Machine 0.

    - Machine 0 (CNC Torna/Freze 1): currently IN_PROGRESS with changeover + first batch.
    - Machine 1 (CNC Torna/Freze 2): alternative eligible machine (slightly slower processing,
      occupied by an earlier job until minute 18).
    - Machine 2 (Taşlama 1) & Machine 3 (Kalite Kontrol): downstream stations.
    """
    if current_time_min < setup_fixed_start_min:
        raise ValueError("current_time_min cannot be earlier than setup_fixed_start_min")
    if setup_remaining_min <= 0:
        raise ValueError("setup_remaining_min must be positive while changeover is active")

    machines = [
        MachineModel(machine_id=0, name="CNC Torna/Freze 1 (Aktif Changeover)"),
        MachineModel(machine_id=1, name="CNC Torna/Freze 2 (Alternatif)"),
        MachineModel(machine_id=2, name="Taşlama 1"),
        MachineModel(machine_id=3, name="Kalite Kontrol"),
    ]

    # J0: Job undergoing active changeover/setup on Machine 0
    # J1: Existing job occupying Machine 1 early on
    # J2: Urgent new order that can use Machine 0 (fast: 12 min) or Machine 1 (slower: 15 min)
    m1_initial_total = 6
    if current_time_min == 0:
        j1_op0 = OperationModel(
            operation_id=0,
            name="Mevcut İşlem (M1)",
            processing_times={1: m1_initial_total},
            duration_source=DurationSource.USER_INPUT,
            status=OperationStatus.NOT_STARTED,
        )
    elif current_time_min < m1_initial_total:
        j1_op0 = OperationModel(
            operation_id=0,
            name="Mevcut İşlem (M1)",
            processing_times={1: m1_initial_total},
            duration_source=DurationSource.USER_INPUT,
            status=OperationStatus.IN_PROGRESS,
            fixed_machine_id=1,
            fixed_start=0,
            remaining_duration=m1_initial_total - current_time_min,
        )
    else:
        j1_op0 = OperationModel(
            operation_id=0,
            name="Mevcut İşlem (M1)",
            processing_times={1: m1_initial_total},
            duration_source=DurationSource.USER_INPUT,
            status=OperationStatus.COMPLETED,
            fixed_machine_id=1,
            fixed_start=0,
            fixed_end=m1_initial_total,
        )

    jobs = [
        JobModel(
            job_id=0,
            name=f"Parti-101 ({transition_label} Setup + İşlem)",
            route_source=RouteSource.USER_APPROVED,
            due_date=35,
            operations=[
                OperationModel(
                    operation_id=0,
                    name=f"CNC Changeover/Setup ({transition_label})",
                    processing_times={0: max(1, current_time_min - setup_fixed_start_min + setup_remaining_min)},
                    duration_source=DurationSource.USER_INPUT,
                    status=OperationStatus.IN_PROGRESS,
                    fixed_machine_id=0,
                    fixed_start=setup_fixed_start_min,
                    remaining_duration=setup_remaining_min,
                ),
                OperationModel(
                    operation_id=1,
                    name="Tornalama Ana İşlem",
                    processing_times={0: 12},
                    duration_source=DurationSource.USER_INPUT,
                ),
                OperationModel(
                    operation_id=2,
                    name="Kalite Kontrol",
                    processing_times={3: 6},
                    duration_source=DurationSource.USER_INPUT,
                ),
            ],
        ),
        JobModel(
            job_id=1,
            name="Parti-102 (Mevcut Sipariş)",
            route_source=RouteSource.USER_APPROVED,
            due_date=28,
            operations=[
                j1_op0,
                OperationModel(
                    operation_id=1,
                    name="Taşlama",
                    processing_times={2: 10},
                    duration_source=DurationSource.USER_INPUT,
                ),
                OperationModel(
                    operation_id=2,
                    name="Kalite Kontrol",
                    processing_times={3: 5},
                    duration_source=DurationSource.USER_INPUT,
                ),
            ],
        ),
        JobModel(
            job_id=2,
            name="Parti-103 (Acil Yeni Sipariş)",
            route_source=RouteSource.USER_APPROVED,
            due_date=32,
            release_time=0,
            operations=[
                OperationModel(
                    operation_id=0,
                    name="Hassas Frezeleme",
                    # Machine 0 is faster (6 min) than Machine 1 (20 min),
                    # so if Machine 0 changeover is long, CP-SAT routes J2 to Machine 1;
                    # once Machine 0 changeover is nearly finished, CP-SAT uses Machine 0.
                    processing_times={0: 6, 1: 20},
                    duration_source=DurationSource.USER_INPUT,
                ),
                OperationModel(
                    operation_id=1,
                    name="Taşlama",
                    processing_times={2: 8},
                    duration_source=DurationSource.USER_INPUT,
                ),
                OperationModel(
                    operation_id=2,
                    name="Kalite Kontrol",
                    processing_times={3: 5},
                    duration_source=DurationSource.USER_INPUT,
                ),
            ],
        ),
    ]

    return WorkshopScenario(
        scenario_id=f"active_changeover_t{current_time_min}",
        description=(
            f"Aktif changeover simülasyonu (t={current_time_min} dk, "
            f"geçiş={transition_label}, kalan setup tahmini={setup_remaining_min} dk)"
        ),
        machines=machines,
        jobs=jobs,
        current_time=current_time_min,
        time_unit="minutes",
        time_unit_note="Canlı CNC changeover kalan süre tahminiyle güncellenen tamsayı dakika.",
    )


def select_checkpoint_rows(
    session_frame: pd.DataFrame, check_minutes: list[int] | None = None
) -> pd.DataFrame:
    """Pick one sensor observation row at each requested elapsed minute checkpoint."""
    if session_frame.empty:
        raise ValueError("Empty session_frame")
    elapsed = pd.to_numeric(
        session_frame["elapsed_changeover_time_min"], errors="raise"
    ).to_numpy(dtype=float)
    max_elapsed = float(np.max(elapsed))
    if check_minutes is None:
        step = max(1, int(round(max_elapsed / 6)))
        check_minutes = sorted(
            {1, *range(step, int(math.floor(max_elapsed)) + 1, step)}
        )
    chosen_indices = []
    for minute in check_minutes:
        if minute > max_elapsed:
            continue
        idx = int(np.argmin(np.abs(elapsed - float(minute))))
        if idx not in chosen_indices:
            chosen_indices.append(idx)
    if not chosen_indices:
        chosen_indices = [0]
    return session_frame.iloc[chosen_indices].copy().reset_index(drop=True)


def simulate_active_changeover(
    session_frame: pd.DataFrame,
    session_actual_remaining: pd.Series | np.ndarray,
    predictor: object,
    *,
    feature_columns: list[str] | None = None,
    check_minutes: list[int] | None = None,
    time_limit_seconds: float = 5.0,
) -> dict:
    """Step through a changeover session in real-time, predicting setup time & solving CP-SAT."""
    work = session_frame.copy().reset_index(drop=True)
    work["__actual_remaining__"] = np.asarray(session_actual_remaining, dtype=float)
    checkpoints = select_checkpoint_rows(work, check_minutes=check_minutes)

    from_prod = (
        str(checkpoints["transition_from_product"].iloc[0])
        if "transition_from_product" in checkpoints
        else "A"
    )
    to_prod = (
        str(checkpoints["transition_to_product"].iloc[0])
        if "transition_to_product" in checkpoints
        else "B"
    )
    transition_label = f"{from_prod}->{to_prod}"

    cols = (
        feature_columns
        if feature_columns is not None
        else [c for c in work.columns if c != "__actual_remaining__"]
    )
    raw_preds = np.asarray(predictor.predict(checkpoints[cols]), dtype=float)

    steps: list[ActiveStepRecord] = []
    elapsed_arr = pd.to_numeric(
        checkpoints["elapsed_changeover_time_min"], errors="raise"
    ).to_numpy(dtype=float)
    actual_arr = checkpoints["__actual_remaining__"].to_numpy(dtype=float)
    for idx, (elapsed_min, actual_rem, pred_rem) in enumerate(
        zip(elapsed_arr, actual_arr, raw_preds)
    ):
        elapsed_min = float(elapsed_min)
        actual_rem = float(actual_rem)
        current_time_min = max(1, int(round(elapsed_min)))
        applied_rem_min = max(1, int(math.ceil(float(pred_rem))))

        scenario = build_active_changeover_scenario(
            current_time_min=current_time_min,
            setup_fixed_start_min=0,
            setup_remaining_min=applied_rem_min,
            transition_label=transition_label,
        )
        env, _, _ = build_env(scenario)
        solved = ScheduleResult.model_validate(solve(env, time_limit=time_limit_seconds))
        metrics = plan_metrics(scenario, solved)

        completions = {j.job_id: j.completion for j in metrics.jobs}
        new_order_op0_machine = next(
            r.source_machine_id
            for r in solved.schedule
            if r.source_job_id == 2 and r.source_operation_id == 0
        )
        steps.append(
            ActiveStepRecord(
                step_index=idx,
                current_time_min=current_time_min,
                elapsed_setup_min=round(elapsed_min, 3),
                actual_remaining_setup_min=round(actual_rem, 3),
                predicted_remaining_setup_min=round(float(pred_rem), 3),
                prediction_error_min=round(float(pred_rem) - actual_rem, 3),
                applied_remaining_duration_min=applied_rem_min,
                estimated_setup_end_min=current_time_min + applied_rem_min,
                actual_setup_end_min=int(round(elapsed_min + actual_rem)),
                schedule_makespan_min=metrics.makespan,
                setup_job_completion_min=completions[0],
                new_order_completion_min=completions[2],
                late_job_count=metrics.late_job_count,
                total_tardiness_min=metrics.total_tardiness,
                new_order_machine_id=new_order_op0_machine,
                alternative_machine_used=(new_order_op0_machine == 1),
                job_completions=completions,
            )
        )

    errors = [abs(s.prediction_error_min) for s in steps]
    return {
        "transition": transition_label,
        "checkpoint_count": len(steps),
        "checkpoint_mae_min": float(np.mean(errors)),
        "machine_routing_changes": sum(
            a.new_order_machine_id != b.new_order_machine_id
            for a, b in zip(steps, steps[1:])
        ),
        "steps": [s.model_dump() for s in steps],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--session-id",
        type=int,
        default=25,
        help="Test split CNC changeover session ID (default: 25)",
    )
    parser.add_argument(
        "--representation",
        choices=["selected", "engineered", "pca"],
        default="selected",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT
        / "reports"
        / "cnc_changeover_model_comparison"
        / "active_simulation_report.json",
    )
    args = parser.parse_args()

    from ml_experiments.compare_duration_models import (
        load_cnc_benchmark_dataset,
        run_comparison,
    )

    ds = load_cnc_benchmark_dataset(representation=args.representation)
    model_dir = (
        ROOT / "reports" / "cnc_changeover_model_comparison" / args.representation
    )
    bundle_path = model_dir / "best_model.joblib"
    if not bundle_path.exists():
        run_comparison(ds, model_dir, include_catboost=True, extended_models=True)
    bundle = joblib.load(bundle_path)
    candidates = bundle["candidates"]
    feature_cols = bundle["features"]

    mask = ds.metadata["group_id"].astype(int).eq(args.session_id)
    if not mask.any():
        available = sorted(
            ds.metadata.loc[ds.metadata.split.eq("test"), "group_id"]
            .astype(int)
            .unique()
            .tolist()
        )
        raise ValueError(
            f"Session {args.session_id} not found. Available test sessions: {available}"
        )

    session_features = ds.features.loc[mask].reset_index(drop=True)
    session_target = ds.y.loc[mask].reset_index(drop=True)

    # Compare active simulation across Median Baseline vs Best ML Model
    winner_name = bundle["model_name"]
    models_to_compare = {"median_baseline": candidates["median"]}
    for name in [
        winner_name,
        "extra_trees",
        "hist_gradient_boosting",
        "catboost",
        "ridge",
    ]:
        if name in candidates and name not in models_to_compare:
            models_to_compare[name] = candidates[name]

    simulations = {}
    for label, cand in models_to_compare.items():
        simulations[label] = simulate_active_changeover(
            session_features,
            session_target,
            cand,
            feature_columns=feature_cols,
            check_minutes=[1, 3, 5, 8, 12, 16, 20],
        )

    report = {
        "session_id": args.session_id,
        "representation": args.representation,
        "selected_winner_model": winner_name,
        "simulations": simulations,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        f"Aktif Changeover Simülasyonu (Seans #{args.session_id}, Temsil={args.representation}) tamamlandı."
    )
    for model_label, sim in simulations.items():
        print(
            f"  - Model: {model_label:24s} | Kontrol Noktası MAE: {sim['checkpoint_mae_min']:.2f} dk | "
            f"Son Makespan: {sim['steps'][-1]['schedule_makespan_min']} dk"
        )


if __name__ == "__main__":
    main()

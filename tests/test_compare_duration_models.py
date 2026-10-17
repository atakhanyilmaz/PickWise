import json

import joblib
import numpy as np
import pandas as pd

from ml_experiments.compare_duration_models import run_comparison
from ml_experiments.duration_features import Dataset


def synthetic_dataset():
    rng = np.random.default_rng(42)
    rows = 90
    quantity = np.tile(np.arange(1, 31), 3)
    activity = np.array(["turning", "milling", "grinding"] * 30)
    part = np.array(["part-a", "part-b", "part-c"] * 30)
    target = quantity * 2.5 + (activity == "milling") * 8 + rng.normal(0, 0.2, rows)
    features = pd.DataFrame(
        {
            "Part Desc.": part,
            "Work Order  Qty": quantity,
            "Activity": activity,
        }
    )
    features.loc[70:, "Part Desc."] = "unseen-part"
    metadata = pd.DataFrame(
        {
            "source_row": np.arange(rows),
            "group_id": np.repeat(np.arange(9), 10),
            "split": ["train"] * 50 + ["validation"] * 20 + ["test"] * 20,
        }
    )
    return Dataset(
        "production_analysis",
        "target_elapsed_time",
        features,
        metadata,
        pd.Series(target),
        [],
        {"target_definition": "synthetic mixed elapsed minutes"},
    )


def test_comparison_is_deterministic_and_writes_contract_artifacts(tmp_path):
    first = run_comparison(synthetic_dataset(), tmp_path / "first", include_catboost=False)
    second = run_comparison(synthetic_dataset(), tmp_path / "second", include_catboost=False)

    assert first["selection"]["winner"] == second["selection"]["winner"]
    for model in first["validation"]:
        assert first["validation"][model]["parameters"] == second["validation"][model]["parameters"]
        for metric in [
            "row_mae_min",
            "group_macro_mae_min",
            "rmse_min",
            "median_absolute_error_min",
            "p90_absolute_error_min",
            "r2",
        ]:
            assert first["validation"][model]["metrics"][metric] == second["validation"][model]["metrics"][metric]
    assert first["features"] == ["Part Desc.", "Activity", "log1p_work_order_qty"]
    assert set(first["split_groups"]) == {"train", "validation", "test"}
    for name in [
        "metrics.json",
        "predictions.csv",
        "all_model_predictions.csv",
        "model_comparison.png",
        "best_model.joblib",
    ]:
        assert (tmp_path / "first" / name).stat().st_size > 0
    model_bundle = joblib.load(tmp_path / "first" / "best_model.joblib")
    assert model_bundle["model_name"] == first["selection"]["winner"]
    assert model_bundle["features"] == first["features"]
    saved = json.loads((tmp_path / "first" / "metrics.json").read_text(encoding="utf-8"))
    assert saved["selection"]["winner"] == first["selection"]["winner"]
    predictions = pd.read_csv(tmp_path / "first" / "predictions.csv")
    assert set(predictions.split) == {"validation", "test"}
    assert predictions.loc[predictions.split.eq("test"), "model"].nunique() == 1
    all_predictions = pd.read_csv(tmp_path / "first" / "all_model_predictions.csv")
    assert set(all_predictions.loc[all_predictions.split.eq("test"), "model"]) == set(
        first["validation"].keys()
    )


def synthetic_cnc_dataset():
    rng = np.random.default_rng(42)
    rows_per_session = 10
    n_sessions = 9
    rows = rows_per_session * n_sessions
    from_prod = np.repeat(["A", "B", "C"] * 3, rows_per_session)
    to_prod = np.repeat(["B", "C", "A"] * 3, rows_per_session)
    elapsed = np.tile(np.linspace(1.0, 14.0, rows_per_session), n_sessions)
    sensor_temp = 40.0 + (from_prod == "A") * 10.0 - elapsed * 0.8 + rng.normal(0, 0.1, rows)
    base_total = np.where(from_prod == "A", 18.0, np.where(from_prod == "B", 15.0, 16.0))
    remaining = np.maximum(0.5, base_total - elapsed - (sensor_temp - 40.0) * 0.15)
    features = pd.DataFrame(
        {
            "transition_from_product": from_prod,
            "transition_to_product": to_prod,
            "elapsed_changeover_time_min": elapsed,
            "Spindle_motor_temperature": sensor_temp,
            "ToolChange_smoothed_current_value": elapsed * 1.2 + rng.normal(0, 0.05, rows),
        }
    )
    metadata = pd.DataFrame(
        {
            "source_row": np.arange(rows),
            "group_id": np.repeat(np.arange(1, n_sessions + 1), rows_per_session),
            "split": (
                ["train"] * (5 * rows_per_session)
                + ["validation"] * (2 * rows_per_session)
                + ["test"] * (2 * rows_per_session)
            ),
        }
    )
    return Dataset(
        "cnc_changeover",
        "remaining_changeover_time_min",
        features,
        metadata,
        pd.Series(remaining, name="remaining_changeover_time_min"),
        [],
        {"target_definition": "synthetic remaining changeover minutes"},
    )


def test_cnc_changeover_benchmark_models_and_metrics(tmp_path):
    ds = synthetic_cnc_dataset()
    report = run_comparison(ds, tmp_path / "cnc_bench", include_catboost=False, extended_models=True)
    expected_models = {
        "median",
        "ridge",
        "elastic_net",
        "huber",
        "knn",
        "random_forest",
        "extra_trees",
        "gradient_boosting",
        "hist_gradient_boosting",
        "mlp",
        "lightgbm",
        "xgboost",
    }
    assert set(report["validation"].keys()) == expected_models
    assert set(report["benchmark_test_summary"].keys()) == expected_models
    assert report["selection"]["winner"] in expected_models
    for m in expected_models:
        assert report["validation"][m]["metrics"]["group_macro_mae_min"] >= 0.0


def test_active_changeover_simulation_updates_setup_and_schedule(tmp_path):
    from core.active_changeover_sim import simulate_active_changeover

    ds = synthetic_cnc_dataset()
    run_comparison(ds, tmp_path / "cnc_sim", include_catboost=False, extended_models=True)
    bundle = joblib.load(tmp_path / "cnc_sim" / "best_model.joblib")
    predictor = bundle["candidates"][bundle["model_name"]]

    # Craft a session where remaining setup starts large (forcing alternative machine 1)
    # and later drops small (allowing fast machine 0)
    session_df = pd.DataFrame(
        {
            "transition_from_product": ["A", "A", "A"],
            "transition_to_product": ["B", "B", "B"],
            "elapsed_changeover_time_min": [1.0, 5.0, 12.0],
            "Spindle_motor_temperature": [50.0, 45.0, 38.0],
            "ToolChange_smoothed_current_value": [1.2, 6.0, 14.0],
        }
    )
    actual_rem = pd.Series([17.0, 11.0, 2.0])

    sim = simulate_active_changeover(
        session_df,
        actual_rem,
        predictor,
        feature_columns=bundle["features"],
        check_minutes=[1, 5, 12],
        time_limit_seconds=2.0,
    )
    assert sim["checkpoint_count"] == 3
    assert sim["transition"] == "A->B"
    steps = sim["steps"]
    assert [s["current_time_min"] for s in steps] == [1, 5, 12]
    # At t=1 with large remaining setup on Machine 0, urgent order J2 uses alternative Machine 1;
    # at t=12 when setup on Machine 0 is nearly finished, J2 switches to faster Machine 0.
    assert steps[0]["alternative_machine_used"] is True
    assert steps[-1]["alternative_machine_used"] is False
    assert sim["machine_routing_changes"] >= 1


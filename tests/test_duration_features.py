"""Leakage barriers and causal feature extraction, using small synthetic data."""

import joblib
import numpy as np
import pandas as pd
import pytest
from threadpoolctl import threadpool_limits

from ml_experiments.duration_features import (
    CNC_FORBIDDEN,
    CNC_METADATA,
    PRODUCTION_FEATURES,
    Dataset,
    DurationSelector,
    artifact_path,
    balanced_indices,
    causal_windows,
    cnc_feature_types,
    errors,
    production_engineering,
    relocate_existing_artifacts,
    run_dataset,
    transform_bundle,
    validate_splits,
    vif_values,
)


def test_train_only_selection_drops_constants_redundancy_and_preserves_schema():
    rng = np.random.default_rng(42)
    x = rng.normal(size=160)
    frame = pd.DataFrame({"useful": x, "duplicate": x * -20,
                          "constant": 7, "near_constant": [0] * 159 + [1],
                          "category": ["A", "B"] * 80})
    train = frame.iloc[:150]
    original = frame.copy(deep=True)
    fitted = DurationSelector(k=2).fit(train, x[:150] ** 2, np.repeat(range(15), 10))
    assert fitted.report_["dropped_features"]["duplicate"] == "correlated_with:useful"
    assert "constant" not in fitted.selected_columns_
    assert "near_constant" not in fitted.selected_columns_
    frame.loc[150:, "constant"] = 1e9
    frame.loc[150:, "category"] = "UNSEEN"
    output = fitted.transform(frame)
    assert output.columns.tolist() == fitted.selected_columns_
    assert output.loc[150:, "category"].eq("UNSEEN").all()
    pd.testing.assert_frame_equal(original.iloc[:150], frame.iloc[:150])
    assert fitted.report_["fit_rows"] == 150


def test_vif_removes_a_linear_combination_not_caught_by_pairwise_correlation():
    rng = np.random.default_rng(6)
    x, y = rng.normal(size=(2, 200))
    frame = pd.DataFrame({"x": x, "y": y, "sum": x + y})
    fitted = DurationSelector(k=3).fit(frame, x * y, np.repeat(range(10), 20))
    assert len(fitted.report_["vif_removals"]) == 1
    assert max(fitted.report_["final_continuous_vif"].values()) <= 20
    assert vif_values(frame[["x"]]) == {"x": 1}


def window_fixture():
    meta = pd.DataFrame({"group_id": [1] * 5 + [2] * 5,
                         "split": ["train"] * 5 + ["test"] * 5,
                         "time": list(pd.date_range("2024-01-01", periods=5, freq="s")) +
                                 list(pd.date_range("2024-01-02", periods=5, freq="s"))})
    frame = pd.DataFrame({"sensor": np.arange(10, dtype=float), "mode": ["A"] * 10})
    return frame, meta


def test_windows_do_not_see_future_and_reset_at_session_boundary():
    frame, meta = window_fixture()
    result = causal_windows(frame, meta, windows=(2, 3))
    assert result.index.tolist() == [2, 3, 4, 7, 8, 9]
    assert result.loc[2, "sensor__mean_3s"] == 1
    assert result.loc[7, "sensor__min_3s"] == 5
    assert result.loc[7, "sensor__delta_3s"] == 2
    # Alter a future measurement and a whole later session.
    modified = frame.copy()
    modified.loc[4:, "sensor"] = 9999
    again = causal_windows(modified, meta, windows=(2, 3))
    pd.testing.assert_frame_equal(result.loc[[2, 3]], again.loc[[2, 3]])
    prefix = causal_windows(frame.iloc[:4], meta.iloc[:4], windows=(2, 3))
    pd.testing.assert_frame_equal(result.loc[prefix.index], prefix)


@pytest.mark.parametrize("bad", ["gap", "split", "order"])
def test_windows_reject_incorrect_history(bad):
    frame, meta = window_fixture()
    if bad == "gap":
        meta.loc[2, "time"] += pd.Timedelta(seconds=2)
    elif bad == "split":
        meta.loc[1, "split"] = "test"
    else:
        meta.loc[2, "time"] = meta.loc[1, "time"]
    with pytest.raises(ValueError):
        causal_windows(frame, meta, windows=(2, 3))


def test_prediction_time_allowlist_and_quantity_extraction():
    assert set(PRODUCTION_FEATURES).isdisjoint({"Qty Rejected", "Qty Completed", "Qty for MRB"})
    assert "history_seconds_available" in CNC_METADATA
    assert "Total_running_time_NC_program" in CNC_FORBIDDEN
    frame = pd.DataFrame({"Work Order  Qty": [0, 10], "Part Desc.": ["a", "b"]})
    result = production_engineering(frame)
    assert "Work Order  Qty" not in result
    np.testing.assert_allclose(result.log1p_work_order_qty, np.log1p([0, 10]))
    assert "Work Order  Qty" in frame
    with pytest.raises(ValueError, match="Negative"):
        production_engineering(pd.DataFrame({"Work Order  Qty": [-1]}))


def test_controller_identifiers_are_nominal_and_redundant_codes_are_removed():
    frame = pd.DataFrame({"Tool_number_slot": [10, 50] * 40,
                          "Magazine_number_slot": [9998, 1] * 40,
                          "Spindle_speed": np.arange(80, dtype=float)})
    typed, columns = cnc_feature_types(frame)
    assert columns == ["Tool_number_slot", "Magazine_number_slot"]
    assert pd.api.types.is_numeric_dtype(typed.Spindle_speed)
    fitted = DurationSelector(k=3).fit(typed, np.arange(80), np.repeat(range(8), 10))
    assert fitted.report_["dropped_features"]["Magazine_number_slot"] == (
        "categorical_bijection_with:Tool_number_slot")


def test_temporal_group_validation_rejects_outcome_overlap():
    meta = pd.DataFrame({"group_id": [1, 2, 3], "split": ["train", "validation", "test"]})
    starts = pd.Series(pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]))
    ends = starts + pd.Timedelta(hours=1)
    validate_splits(meta, starts, ends)
    ends[0] = starts[1] + pd.Timedelta(hours=1)
    with pytest.raises(ValueError, match="overlap"):
        validate_splits(meta, starts, ends)


def test_group_macro_metric_and_balanced_sampling_do_not_favor_long_sessions():
    result = errors([0, 0, 0, 0], [1, 1, 1, 9], ["long"] * 3 + ["short"])
    assert result["row_mae_min"] == 3
    assert result["group_macro_mae_min"] == 5
    idx = balanced_indices(["long"] * 100 + ["short"] * 5, limit=10)
    assert sum(idx < 100) == sum(idx >= 100) == 5


def synthetic_production():
    rng = np.random.default_rng(4)
    n = 90
    x = pd.DataFrame({"Part Desc.": ["a", "b", "c"] * 30,
                      "Work Order  Qty": rng.integers(1, 50, n),
                      "Activity": ["turning", "milling"] * 45})
    meta = pd.DataFrame({"source_row": np.arange(n), "group_id": np.repeat(np.arange(9), 10),
                         "split": ["train"] * 50 + ["validation"] * 20 + ["test"] * 20})
    y = x["Work Order  Qty"].astype(float) * 3 + rng.random(n)
    return Dataset("production_analysis", "target_elapsed_time", x, meta, y, [], {})


def test_export_reload_and_frozen_train_state_when_holdout_changes(tmp_path):
    dataset = synthetic_production()
    with threadpool_limits(limits=1):
        report = run_dataset(dataset, tmp_path / "first")
    saved = joblib.load(tmp_path / "first/transformers.joblib")
    repeated = transform_bundle(saved, dataset.features)
    exported = pd.read_csv(report["artifacts"]["extracted"]["path"])
    np.testing.assert_allclose(repeated, exported[repeated.columns], rtol=1e-7, atol=1e-7)
    assert report["extraction"]["pca_retained_variance"] >= .95
    assert set(report["selection"]["selected_features"]) <= set(PRODUCTION_FEATURES)
    assert all(c not in saved["extraction_encoder"].get_feature_names_out()
               for c in ["split", "group_id", "target_elapsed_time"])
    # Neither selection, imputers, scalers, category vocabulary nor PCA may depend on holdout.
    dataset.features.loc[50:, "Work Order  Qty"] = 1e6
    dataset.features.loc[50:, "Part Desc."] = "UNSEEN"
    dataset.y.loc[50:] = 1e5
    with threadpool_limits(limits=1):
        second = run_dataset(dataset, tmp_path / "second")
    after = joblib.load(tmp_path / "second/transformers.joblib")
    assert report["selection"] == second["selection"]
    np.testing.assert_array_equal(saved["pca"].components_, after["pca"].components_)
    np.testing.assert_array_equal(saved["pca_scaler"].mean_, after["pca_scaler"].mean_)
    np.testing.assert_array_equal(saved["extraction_encoder"].get_feature_names_out(),
                                  after["extraction_encoder"].get_feature_names_out())


def test_layout_contains_exactly_three_primary_training_csvs(tmp_path):
    primary = tmp_path / "biPre"
    paths = [artifact_path(dataset, kind, primary)
             for dataset in ["production_analysis", "cnc_changeover"]
             for kind in ["selected", "engineered", "extracted"]]
    assert {p.name for p in paths if p.parent == primary} == {
        "production_analysis_engineered.csv", "cnc_changeover_selected.csv",
        "cnc_changeover_extracted.csv",
    }
    assert all(p.is_relative_to(tmp_path) for p in paths)


def test_relocation(tmp_path):
    import json

    dataset = synthetic_production()
    report_dir = tmp_path / "reports"
    folder = report_dir / dataset.name
    with threadpool_limits(limits=1):
        report = run_dataset(dataset, folder, data_output=tmp_path / "d")
    # Simulate the previous flat report-directory artifact layout.
    for artifact in report["artifacts"].values():
        from pathlib import Path

        previous = Path(artifact["path"])
        legacy = folder / previous.name
        previous.rename(legacy)
        artifact["path"] = str(legacy)
    (folder / "report.json").write_text(json.dumps(report), encoding="utf-8")
    primary = tmp_path / "data/biPre"
    relocated = relocate_existing_artifacts(report_dir, primary, [dataset.name])
    assert len(relocated) == 3
    assert [p.name for p in primary.glob("*.csv")] == ["production_analysis_engineered.csv"]
    updated = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    for kind, old in report["artifacts"].items():
        assert updated["artifacts"][kind]["sha256"] == old["sha256"]
        assert not (folder / Path(old["path"]).name).exists()
    assert relocate_existing_artifacts(report_dir, primary, [dataset.name]) == relocated

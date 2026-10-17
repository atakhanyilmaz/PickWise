"""Feature timing, held-out exclusion and case-weighted evaluation checks."""

import numpy as np
import pandas as pd
import pytest

from experiments.tabpfn.learnability import datasets, improvement_interval, score
from experiments.tabpfn.process_target_audit import named_machine


def source():
    rows = []
    for i, split in enumerate(["train", "train", "validation", "test"]):
        start = pd.Timestamp("2024-01-01") + pd.Timedelta(days=i)
        for op, offset in enumerate([0, 10]):
            rows.append(
                {
                    "Case ID": f"case{i}",
                    "Activity": f"op{op}",
                    "Resource": ["Machine 10 - Grinding", "Machine 14 - Milling"][op],
                    "Start Timestamp": str(start + pd.Timedelta(minutes=offset)),
                    "Complete Timestamp": str(start + pd.Timedelta(minutes=offset + 1)),
                    "Part Desc.": "known",
                    "Work Order  Qty": 10,
                }
            )
    manifest = pd.DataFrame(
        {
            "group_id": [f"case{i}" for i in range(4)],
            "split": ["train", "train", "validation", "test"],
        }
    )
    return pd.DataFrame(rows), manifest


def test_all_machine_types_are_counted_not_just_turning_milling():
    assert named_machine("Machine 10 - Grinding")
    assert named_machine("Wire Cut - Machine 13")
    assert not named_machine("Quality Check 1")
    raw, manifest = source()
    tasks, _ = datasets(raw, manifest)
    train, valid, features, _, _ = tasks["conditional_machine_gap"]
    assert len(train) == 2 and len(valid) == 1
    assert train.y.tolist() == [9, 9]
    assert features == ["part", "quantity", "from", "to"]


def test_test_features_and_outcomes_do_not_change_train_or_validation():
    raw, manifest = source()
    before, _ = datasets(raw, manifest)
    mask = raw["Case ID"].eq("case3")
    raw.loc[mask, "Part Desc."] = "unseen-test-only"
    raw.loc[mask, "Work Order  Qty"] = 999
    raw.loc[mask, "Complete Timestamp"] = "2024-01-04 23:00:00"
    after, _ = datasets(raw, manifest)
    for task in before:
        for i in (0, 1):
            pd.testing.assert_frame_equal(before[task][i], after[task][i])
        assert "case3" not in set(after[task][0].case) | set(after[task][1].case)


def test_temporal_leakage_stops_experiment():
    raw, manifest = source()
    manifest.loc[manifest.group_id.eq("case0"), "split"] = "validation"
    with pytest.raises(ValueError, match="unavailable"):
        datasets(raw, manifest)


def test_case_macro_metrics_do_not_overweight_repeated_rows():
    frame = pd.DataFrame({"case": ["a", "a", "b"], "y": [0.0, 0.0, 0.0]})
    actual = score(frame, [10, 10, 30])
    assert actual["case_macro_mae_minutes"] == 20
    assert actual["mae_minutes"] == pytest.approx(50 / 3)
    interval = improvement_interval(frame, [10, 10, 30], [0, 0, 0])
    assert interval["case_macro_mae_improvement_minutes"] == 20
    assert interval["case_count"] == 2


def test_predictions_must_be_finite_and_complete():
    frame = pd.DataFrame({"case": ["a"], "y": [1.0]})
    with pytest.raises(ValueError):
        score(frame, [np.nan])
    with pytest.raises(ValueError):
        score(frame, [])

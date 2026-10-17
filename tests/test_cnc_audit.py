"""Small deliberate corruptions test the read-only CNC audit."""

import pandas as pd
import pytest

from ml_experiments.cnc_audit import audit


@pytest.fixture
def frames():
    times = pd.date_range("2024-01-01", periods=12, freq="s").astype(str)
    raw = pd.DataFrame(
        {"time": times, "Label_03": [0, 0, 0, 1] * 3, "sensor": [None, 2, 3, 4] * 3}
    )
    target = raw[raw.Label_03.eq(0)].drop(columns="Label_03").reset_index(drop=True)
    target["sensor__was_missing"] = target.sensor.isna().astype(int)
    target["sensor"] = target.sensor.fillna(-1)
    target["changeover_session_id"] = [1] * 3 + [2] * 3 + [3] * 3
    target["split"] = ["train"] * 3 + ["validation"] * 3 + ["test"] * 3
    target["transition_from_product"] = "A"
    target["transition_to_product"] = "B"
    target["elapsed_changeover_time_min"] = [0, 1 / 60, 2 / 60] * 3
    target["remaining_changeover_time_min"] = [2 / 60, 1 / 60, 0] * 3
    target["history_seconds_available"] = [1, 2, 3] * 3
    target["eligible_for_30s_window"] = False
    target["eligible_for_60s_window"] = False
    return raw, target


def test_valid_audit_preserves_inputs_and_reports_boundary(frames):
    raw, target = frames
    original_raw, original_target = raw.copy(deep=True), target.copy(deep=True)
    report = audit(raw, target)
    assert report["numeric_checks_passed"]
    assert not report["operational_use_approved"]
    assert report["sessions"][0]["next_sample_gap_seconds"] == 1
    assert report["sessions"][0]["next_label03"] == 1
    pd.testing.assert_frame_equal(raw, original_raw)
    pd.testing.assert_frame_equal(target, original_target)


@pytest.mark.parametrize(
    "column,value,message",
    [
        ("remaining_changeover_time_min", 99, "Remaining target"),
        ("split", "test", "crosses splits"),
        ("sensor", 999, "Observed raw values changed"),
        ("sensor__was_missing", 1, "Incorrect missing provenance"),
        ("changeover_session_id", 9, "Session IDs disagree"),
        ("eligible_for_30s_window", True, "window eligibility"),
    ],
)
def test_corruptions_rejected(frames, column, value, message):
    raw, target = frames
    target.loc[1, column] = value
    result = audit(raw, target)
    assert not result["numeric_checks_passed"]
    assert any(message in e for e in result["errors"])


def test_missing_target_row_rejected(frames):
    raw, target = frames
    result = audit(raw, target.iloc[1:])
    assert not result["numeric_checks_passed"]
    assert any("coverage" in e for e in result["errors"])


def test_invalid_timestamp_and_missing_columns_fail_cleanly(frames):
    raw, target = frames
    target.loc[0, "time"] = "invalid"
    assert not audit(raw, target)["numeric_checks_passed"]
    assert not audit(raw, target.drop(columns="split"))["numeric_checks_passed"]

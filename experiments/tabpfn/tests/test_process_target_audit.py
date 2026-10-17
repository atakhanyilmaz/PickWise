"""Observable report intervals must not be mistaken for verified routes."""

import pandas as pd
import pytest

from experiments.tabpfn.process_target_audit import analyze


def frames():
    raw = pd.DataFrame(
        {
            "Case ID": ["one", "one", "one", "two"],
            "Activity": ["a", "b", "c", "a"],
            "Resource": ["Machine A", "Machine B", "Quality", "Machine A"],
            "Start Timestamp": [
                "2024-01-01 00:00",
                "2024-01-01 00:05",
                "2024-01-01 00:20",
                "2024-01-02 00:00",
            ],
            "Complete Timestamp": [
                "2024-01-01 00:10",
                "2024-01-01 00:06",
                "2024-01-01 00:22",
                "2024-01-02 00:30",
            ],
            "Part Desc.": ["part"] * 4,
            "Work Order  Qty": [10] * 4,
        }
    )
    manifest = pd.DataFrame({"group_id": ["one", "two"], "split": ["train", "test"]})
    return raw, manifest


def test_overlaps_do_not_become_negative_transfer_training_labels():
    raw, manifest = frames()
    before = raw.copy(deep=True)
    report, cases, pairs = analyze(raw, manifest)
    assert report["negative_gap_pairs"] == 1
    assert report["cases_with_overlapping_intervals"] == 1
    assert not pairs.iloc[0].nonnegative_unambiguous_timestamps
    assert cases.iloc[0].observed_case_span_minutes == 22
    assert not report["observed_case_span_is_verified_order_lead_time"]
    pd.testing.assert_frame_equal(raw, before)


def test_nonadjacent_overlap_is_detected():
    raw, manifest = frames()
    raw.loc[2, "Start Timestamp"] = "2024-01-01 00:07"
    raw.loc[2, "Complete Timestamp"] = "2024-01-01 00:08"
    report, _, pairs = analyze(raw, manifest)
    assert report["timestamp_screened_pairs"] == 0
    # Although B ends before C starts, A is still running at C's start.
    assert pairs.iloc[1].observed_adjacent_gap_minutes == 1
    assert not pairs.iloc[1].nonnegative_unambiguous_timestamps


def test_duplicate_and_tied_reports_are_marked_without_deletion():
    raw, manifest = frames()
    raw = pd.concat([raw, raw.iloc[[0]]], ignore_index=True)
    report, cases, _ = analyze(raw, manifest)
    assert report["exact_duplicate_excess_rows"] == 1
    assert report["cases_with_tied_starts"] == 1
    assert cases.rows.sum() == 5


def test_case_split_conflict_rejected():
    raw, manifest = frames()
    manifest = pd.concat(
        [manifest, pd.DataFrame({"group_id": ["one"], "split": ["test"]})]
    )
    with pytest.raises(ValueError, match="multiple splits"):
        analyze(raw, manifest)


def test_invalid_timestamp_and_missing_mapping_rejected():
    raw, manifest = frames()
    with pytest.raises(ValueError, match="Missing case"):
        analyze(raw, manifest.iloc[:1])
    raw.loc[0, "Complete Timestamp"] = "2023-01-01"
    with pytest.raises(ValueError, match="reversed"):
        analyze(raw, manifest)

from pathlib import Path

import pandas as pd

from ml_experiments.prepare_data import (
    build_cnc_remaining_time_dataset,
    build_production_target_dataset,
)


def test_build_production_target_dataset_filters_ambiguous_durations_and_drops_leakage():
    frame = pd.DataFrame(
        {
            "Case ID": ["ok", "rounding", "zero", "mismatch", "missing_span"],
            "Activity": ["A", "B", "C", "D", "E"],
            "Start Timestamp": ["2024-01-01 08:00"] * 5,
            "Complete Timestamp": [
                "2024-01-01 08:30",
                "2024-01-01 08:31",
                "2024-01-01 08:00",
                "2024-01-01 09:00",
                "2024-01-01 08:15",
            ],
            "Span": ["000:30", "000:30", "000:00", "000:10", None],
            "Rework": [None, None, "Y", None, None],
            "Report Type": ["D", "S", "B", "D", "S"],
            "start_parsed": ["unused"] * 5,
            "complete_parsed": ["unused"] * 5,
            "timestamp_elapsed_min": [30, 31, 0, 60, 15],
            "span_recorded_min": [30, 30, 0, 10, None],
            "span_minus_elapsed_min": [0, -1, 0, -50, None],
        }
    )

    prepared, report = build_production_target_dataset(frame)

    assert prepared["Case ID"].tolist() == ["ok", "rounding"]
    assert prepared["target_elapsed_time"].tolist() == [30.0, 31.0]
    for column in [
        "Rework",
        "Report Type",
        "Start Timestamp",
        "Complete Timestamp",
        "Span",
        "start_parsed",
        "complete_parsed",
        "timestamp_elapsed_min",
        "span_recorded_min",
        "span_minus_elapsed_min",
    ]:
        assert column not in prepared.columns
    assert report["removed_row_reasons"] == {
        "invalid_timestamp": 0,
        "non_positive_elapsed_time": 1,
        "invalid_or_missing_span": 1,
        "span_elapsed_mismatch_over_tolerance": 1,
    }
    assert report["report_type_counts_before_removal"] == {"D": 1, "S": 1}
    assert report["report_type_meanings"]["B"] == "breakdown"


def test_build_production_target_dataset_requires_source_time_fields():
    frame = pd.DataFrame({"Start Timestamp": [], "Complete Timestamp": [], "Span": []})

    try:
        build_production_target_dataset(frame)
    except ValueError as error:
        assert "Rework" in str(error)
    else:
        raise AssertionError("Expected missing Rework column to be rejected")


def test_readme_records_new_order_input_contract():
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")

    for required_text in [
        "Yeni Sipariş İçin Gerekli Bilgiler",
        "Ürün kodu",
        "Sipariş miktarı",
        "NC programı",
        "Parça geçiş matrisi",
        "canlı CNC sensör bağlantısı",
    ]:
        assert required_text in readme


def test_build_cnc_remaining_time_dataset_keeps_sessions_whole_and_drops_labels():
    frame = pd.DataFrame(
        {
            "source_row_index": range(8),
            "time": pd.date_range("2024-01-01 08:00:00", periods=8, freq="s").astype(str),
            "Label_03": [0, 0, 0, 0, 1, 1, 1, 1],
            "Label_09": [2, 2, 2, 2, 6, 6, 6, 6],
            "Label_10": [1, 1, 2, 2, 40, 40, 40, 40],
            "Line_Content": ["__NO_NC_LINE__", "G01 X1", "G01 X2", "__NO_NC_LINE__", None, None, None, None],
            "Line_Content__was_missing": [1, 0, 0, 1, 1, 1, 1, 1],
            "sensor": range(8),
            "Program_Stop": [False] * 8,
        }
    )

    prepared, report = build_cnc_remaining_time_dataset(frame)

    assert prepared["changeover_session_id"].tolist() == [1, 1, 1, 1]
    assert prepared["remaining_changeover_time_min"].round(6).tolist() == [
        round(3 / 60, 6),
        round(2 / 60, 6),
        round(1 / 60, 6),
        0.0,
    ]
    assert prepared["transition_from_product"].tolist() == ["A"] * 4
    assert prepared["transition_to_product"].tolist() == ["B"] * 4
    assert prepared["split"].tolist() == ["train"] * 4
    assert not any(column.startswith("Label_") for column in prepared.columns)
    assert "Program_Stop" not in prepared.columns
    assert "source_row_index" not in prepared.columns
    assert "Line_Content" not in prepared.columns
    assert "Line_Content__was_missing" not in prepared.columns
    assert prepared["nc_line_is_active"].tolist() == [0, 1, 1, 0]
    assert report["changeover_sessions"] == 1


def test_build_cnc_remaining_time_dataset_rejects_gaps_inside_changeover():
    frame = pd.DataFrame(
        {
            "time": ["2024-01-01 08:00:00", "2024-01-01 08:00:02"],
            "Label_03": [0, 0],
            "Label_09": [2, 2],
        }
    )

    try:
        build_cnc_remaining_time_dataset(frame)
    except ValueError as error:
        assert "non-one-second" in str(error)
    else:
        raise AssertionError("Expected a changeover sampling gap to be rejected")

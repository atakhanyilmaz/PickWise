"""Synthetic contract checks; no real production-data/model performance claim."""

import pytest
from pydantic import ValidationError

from ml_experiments.duration_evaluation import (
    DurationDataset,
    evaluate_duration,
    feature_rows,
)


def record(rid, job, start, end, duration, operation="turning"):
    return dict(
        record_id=rid,
        job_id=job,
        part_desc="synthetic_part",
        operation_type=operation,
        machine_id="M1",
        batch_size=1,
        started_at=f"2026-10-16T{start}:00+03:00",
        finished_at=f"2026-10-16T{end}:00+03:00",
        duration_minutes=duration,
    )


def data():
    return dict(
        source="synthetic test",
        source_version="v1",
        target_definition="recorded_elapsed_minutes",
        target_reviewed=True,
        train=[
            record("r1", "j1", "08:00", "08:10", 10),
            record("r2", "j2", "09:00", "09:20", 20),
        ],
        test=[
            record("r3", "j3", "10:00", "10:25", 25),
            record("r4", "j4", "11:00", "11:05", 5, "unseen"),
        ],
    )


def test_training_only_median_and_unseen_fallback():
    dataset = DurationDataset.model_validate(data())
    report = evaluate_duration(dataset)
    assert report["median_predictions"] == [15, 15]
    assert report["median"]["mae_minutes"] == 10
    assert report["model"] is None
    assert report["test_job_count"] == 2


@pytest.mark.parametrize(
    "kind", ["group", "future", "duplicate", "fingerprint", "span", "review"]
)
def test_reject_leakage_duplicate_or_unreviewed_target(kind):
    values = data()
    if kind == "group":
        values["test"][0]["job_id"] = "j1"
    elif kind == "future":
        values["train"][0] = record("r1", "j1", "12:00", "12:10", 10)
    elif kind == "duplicate":
        values["test"][0]["record_id"] = "r1"
    elif kind == "fingerprint":
        values["train"][1] = {**values["train"][0], "record_id": "r2"}
    elif kind == "span":
        values["train"][0]["duration_minutes"] = 999
    else:
        values["target_reviewed"] = False
    with pytest.raises(ValidationError):
        DurationDataset.model_validate(values)


def test_features_exclude_actual_outcomes_and_future_fields():
    features = feature_rows(DurationDataset.model_validate(data()).train)
    assert set(features[0]) == {
        "part_desc",
        "operation_type",
        "machine_id",
        "batch_size",
    }


def test_predictor_receives_only_allowed_features():
    class Predictor:
        def fit(self, features, targets):
            assert set(features[0]) == {
                "part_desc",
                "operation_type",
                "machine_id",
                "batch_size",
            }
            assert targets == [10, 20]

        def predict(self, features):
            return [24, 6]

    report = evaluate_duration(
        DurationDataset.model_validate(data()),
        Predictor(),
        {"name": "test_double", "version": "1"},
    )
    assert report["model"]["mae_minutes"] == 1
    assert report["model_beats_median_mae"] is True


def test_verified_processing_duration_may_differ_from_elapsed():
    values = data()
    values["target_definition"] = "verified_processing_minutes"
    values["train"][0]["duration_minutes"] = 7
    assert DurationDataset.model_validate(values).train[0].duration_minutes == 7

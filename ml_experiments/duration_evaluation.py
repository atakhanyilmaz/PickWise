"""Reviewed train/test contracts and median baseline. No model download or training by default."""

import argparse
import json
from math import isfinite, sqrt
from pathlib import Path
from statistics import median
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from core.domain_rules import Contract, Positive


class DurationRecord(Contract):
    record_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    part_desc: str = Field(min_length=1)
    operation_type: str = Field(min_length=1)
    machine_id: str = Field(min_length=1)
    batch_size: Positive
    started_at: AwareDatetime
    finished_at: AwareDatetime
    duration_minutes: float = Field(gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def valid_time(self):
        if self.finished_at <= self.started_at:
            raise ValueError("finished_at must be after started_at")
        return self


class DurationDataset(Contract):
    source: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    target_definition: Literal[
        "recorded_elapsed_minutes", "verified_processing_minutes"
    ]
    target_reviewed: bool
    train: list[DurationRecord] = Field(min_length=1)
    test: list[DurationRecord] = Field(min_length=1)

    @model_validator(mode="after")
    def no_leakage(self):
        if not self.target_reviewed:
            raise ValueError(
                "Human target-definition review is required before evaluation"
            )
        all_rows = self.train + self.test
        if len({r.record_id for r in all_rows}) != len(all_rows):
            raise ValueError("Duplicate record IDs")
        fingerprints = {
            (r.job_id, r.operation_type, r.machine_id, r.started_at, r.finished_at)
            for r in all_rows
        }
        if len(fingerprints) != len(all_rows):
            raise ValueError(
                "Repeated event fingerprints; review duplicates rather than silently dropping them"
            )
        if {r.job_id for r in self.train} & {r.job_id for r in self.test}:
            raise ValueError("Same job occurs in train and test")
        if max(r.finished_at for r in self.train) > min(
            r.started_at for r in self.test
        ):
            raise ValueError(
                "Training outcomes are not all available before the first test prediction"
            )
        if self.target_definition == "recorded_elapsed_minutes":
            for row in all_rows:
                elapsed = (row.finished_at - row.started_at).total_seconds() / 60
                if abs(elapsed - row.duration_minutes) > 1e-6:
                    raise ValueError(
                        "Duration differs from elapsed time for elapsed target; inspect span meaning"
                    )
        return self


def metrics(actual, predicted):
    if len(actual) != len(predicted) or not actual:
        raise ValueError("Prediction count must match nonempty test set")
    if any(not isfinite(float(v)) or v <= 0 for v in predicted):
        raise ValueError("Predicted durations must be finite and positive")
    errors = [float(p) - float(y) for y, p in zip(actual, predicted)]
    return {
        "mae_minutes": sum(abs(e) for e in errors) / len(errors),
        "rmse_minutes": sqrt(sum(e * e for e in errors) / len(errors)),
        "sample_count": len(errors),
    }


def median_predictions(dataset: DurationDataset):
    """Operation median; unseen operations fall back to training-only global median."""
    grouped = {}
    for row in dataset.train:
        grouped.setdefault(row.operation_type, []).append(row.duration_minutes)
    medians = {key: median(values) for key, values in grouped.items()}
    fallback = median([r.duration_minutes for r in dataset.train])
    return [medians.get(r.operation_type, fallback) for r in dataset.test]


def feature_rows(records):
    # Explicit allowlist excludes all outcomes, timestamps and future summaries.
    return [
        {
            key: getattr(r, key)
            for key in ("part_desc", "operation_type", "machine_id", "batch_size")
        }
        for r in records
    ]


def evaluate_duration(dataset: DurationDataset, predictor=None, model_metadata=None):
    dataset = DurationDataset.model_validate(dataset.model_dump())
    actual = [r.duration_minutes for r in dataset.test]
    reference = median_predictions(dataset)
    report = {
        "source": dataset.source,
        "source_version": dataset.source_version,
        "target_definition": dataset.target_definition,
        "time_unit": "minutes",
        "split_method": "provided job-disjoint chronological holdout; all training outcomes precede test starts",
        "train_samples": len(dataset.train),
        "test_samples": len(dataset.test),
        "train_job_count": len({r.job_id for r in dataset.train}),
        "test_job_count": len({r.job_id for r in dataset.test}),
        "test_parts": sorted({r.part_desc for r in dataset.test}),
        "median": metrics(actual, reference),
        "median_predictions": reference,
        "fallback": "Unseen operation_type -> training global median",
        "model": None,
        "model_metadata": None,
    }
    if predictor is not None:
        if (
            not model_metadata
            or not model_metadata.get("name")
            or not model_metadata.get("version")
        ):
            raise ValueError("Model name and version metadata required")
        # External predictor must handle categories within its train-only pipeline.
        predictor.fit(
            feature_rows(dataset.train), [r.duration_minutes for r in dataset.train]
        )
        predictions = list(predictor.predict(feature_rows(dataset.test)))
        report["model"] = metrics(actual, predictions)
        report["model_metadata"] = model_metadata
        report["model_beats_median_mae"] = (
            report["model"]["mae_minutes"] < report["median"]["mae_minutes"]
        )
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, default=Path("results/duration_experiment.json")
    )
    args = parser.parse_args()
    dataset = DurationDataset.model_validate_json(args.dataset.read_text())
    result = evaluate_duration(dataset)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("Medyan MAE:", result["median"]["mae_minutes"], "dakika")
    print("TabPFN çalıştırılmadı; bu rapor yalnız medyan referansıdır.")


if __name__ == "__main__":
    main()

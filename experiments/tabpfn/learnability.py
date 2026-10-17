"""Train-only models, validation-only scores for two retrospective targets."""

import argparse
import hashlib
import json
import os
import time
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd

from experiments.tabpfn.process_target_audit import analyze

ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT = Path(__file__).resolve().parent


def datasets(raw, manifest):
    report, cases, pairs = analyze(raw, manifest)
    grouped = raw.groupby("Case ID", sort=False)
    if (
        grouped["Part Desc."].nunique(dropna=False).ne(1).any()
        or grouped["Work Order  Qty"].nunique(dropna=False).ne(1).any()
    ):
        raise ValueError("Part/quantity not constant within case")
    source = grouped.first()
    part = source["Part Desc."].to_dict()
    qty = source["Work Order  Qty"].to_dict()
    total = cases.rename(
        columns={"case_id": "case", "observed_case_span_minutes": "y"}
    ).copy()
    total["part"] = total.case.map(part)
    total["quantity"] = total.case.map(qty)
    gaps = pairs[
        pairs.nonnegative_unambiguous_timestamps & pairs.both_named_machining_resources
    ].copy()
    gaps = gaps.rename(
        columns={
            "case_id": "case",
            "observed_adjacent_gap_minutes": "y",
            "resource_a": "from",
            "resource_b": "to",
        }
    )
    gaps["part"] = gaps.case.map(part)
    gaps["quantity"] = gaps.case.map(qty)
    # No test outcomes are used for fitting, tuning or model scoring.
    outputs = {}
    for name, frame, features, category, median_keys in (
        ("total_case_span", total, ["part", "quantity"], ["part"], ["part"]),
        (
            "conditional_machine_gap",
            gaps,
            ["part", "quantity", "from", "to"],
            ["part", "from", "to"],
            ["from", "to"],
        ),
    ):
        train = frame[frame.split.eq("train")].copy()
        valid = frame[frame.split.eq("validation")].copy()
        if train.empty or valid.empty:
            raise ValueError(f"Empty train/validation for {name}")
        if set(train.case) & set(valid.case):
            raise ValueError("Case split leakage")
        train_cases = cases[cases.case_id.isin(train.case)]
        valid_cases = cases[cases.case_id.isin(valid.case)]
        if (
            pd.to_datetime(train_cases.end).max()
            >= pd.to_datetime(valid_cases.start).min()
        ):
            raise ValueError("Training outcomes unavailable before validation starts")
        for part_frame in (train, valid):
            if part_frame[features + ["y"]].isna().any().any():
                raise ValueError("Missing features or target")
            if not np.isfinite(part_frame.y).all() or part_frame.y.lt(0).any():
                raise ValueError("Invalid target")
        outputs[name] = (train, valid, features, category, median_keys)
    return outputs, report


def score(frame, predictions):
    predictions = np.asarray(predictions, dtype=float)
    if predictions.shape != (len(frame),) or not np.isfinite(predictions).all():
        raise ValueError("Invalid prediction vector")
    error = predictions - frame.y.to_numpy()
    group_mae = pd.Series(np.abs(error), index=frame.index).groupby(frame.case).mean()
    return {
        "mae_minutes": float(np.abs(error).mean()),
        "rmse_minutes": float(np.sqrt(np.mean(error**2))),
        "case_macro_mae_minutes": float(group_mae.mean()),
        "max_absolute_error_minutes": float(np.abs(error).max()),
    }


def improvement_interval(frame, baseline, candidate):
    # Paired bootstrap by whole case: no false independence of sensor/report rows.
    delta = np.abs(np.asarray(baseline) - frame.y.to_numpy()) - np.abs(
        np.asarray(candidate) - frame.y.to_numpy()
    )
    values = pd.Series(delta, index=frame.index).groupby(frame.case).mean().to_numpy()
    rng = np.random.default_rng(0)
    means = rng.choice(values, size=(2000, len(values)), replace=True).mean(axis=1)
    return {
        "case_macro_mae_improvement_minutes": float(values.mean()),
        "bootstrap_95_percent_interval_minutes": [
            float(x) for x in np.quantile(means, [0.025, 0.975])
        ],
        "case_count": len(values),
        "interpretation": "positive favors candidate; exploratory validation interval, not production assurance",
    }


def run_task(name, data, with_tabpfn, device, output):
    from sklearn.compose import ColumnTransformer
    from sklearn.ensemble import ExtraTreesRegressor
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder

    train, valid, features, categories, keys = data
    x, y = train[features].copy(), train.y.to_numpy()
    xv = valid[features].copy()
    med = float(np.median(y))
    group_medians = train.groupby(keys).y.median().to_dict()
    key_values = [
        tuple(row) if len(keys) > 1 else row[0]
        for row in valid[keys].itertuples(index=False, name=None)
    ]
    predictions = {
        "global_median": np.full(len(valid), med),
        "group_median": np.array([group_medians.get(k, med) for k in key_values]),
    }
    metadata = {
        "features": features,
        "train_rows": len(train),
        "train_cases": int(train.case.nunique()),
        "validation_rows": len(valid),
        "validation_cases": int(valid.case.nunique()),
        "group_median_fallback_count": sum(k not in group_medians for k in key_values),
        "unseen_category_rows": {},
        "runtime_seconds": {},
        "model_status": {},
    }
    metadata["unseen_category_rows"] = {
        c: int((~xv[c].isin(x[c])).sum()) for c in categories
    }
    numeric = [c for c in features if c not in categories]
    prep = ColumnTransformer(
        [
            (
                "cat",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                categories,
            ),
            ("numeric", "passthrough", numeric),
        ]
    )
    simple = make_pipeline(
        prep,
        ExtraTreesRegressor(
            n_estimators=100, max_depth=4, min_samples_leaf=3, random_state=0, n_jobs=1
        ),
    )
    started = time.monotonic()
    simple.fit(x, y)
    predictions["extra_trees"] = np.maximum(0, simple.predict(xv))
    metadata["runtime_seconds"]["extra_trees"] = time.monotonic() - started
    if with_tabpfn:
        from tabpfn import TabPFNRegressor
        from tabpfn.constants import ModelVersion

        # Explicit categorical codes fitted only on training rows.
        enc = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)
        xt, xvt = x.copy(), xv.copy()
        xt[categories] = enc.fit_transform(x[categories])
        xvt[categories] = enc.transform(xv[categories])
        model = TabPFNRegressor.create_default_for_version(
            ModelVersion.V2,
            device=device,
            random_state=0,
            n_estimators=4,
            categorical_features_indices=[features.index(c) for c in categories],
        )
        started = time.monotonic()
        try:
            model.fit(xt.to_numpy(dtype=float), y)
            predictions["tabpfn_v2"] = np.maximum(
                0, np.asarray(model.predict(xvt.to_numpy(dtype=float)))
            )
            metadata["model_status"]["tabpfn_v2"] = "real_model_completed"
        except Exception as exc:
            metadata["model_status"]["tabpfn_v2"] = {
                "error_type": type(exc).__name__,
                "message": str(exc)[:1200],
            }
        metadata["runtime_seconds"]["tabpfn_v2"] = time.monotonic() - started
    metadata["validation_scores"] = {m: score(valid, p) for m, p in predictions.items()}
    metadata["paired_validation_improvement_over_global_median"] = {
        m: improvement_interval(valid, predictions["global_median"], p)
        for m, p in predictions.items()
        if m != "global_median"
    }
    metadata["paired_validation_improvement_over_group_median"] = {
        m: improvement_interval(valid, predictions["group_median"], p)
        for m, p in predictions.items()
        if m not in ("global_median", "group_median")
    }
    export = valid[["case", "y"] + features].copy()
    for m, p in predictions.items():
        export[m] = p
    export.to_csv(output / f"{name}_validation_predictions.csv", index=False)
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tabpfn", action="store_true")
    parser.add_argument("--device", default="cpu", choices=["cpu", "mps"])
    parser.add_argument(
        "--output", type=Path, default=EXPERIMENT / "results" / "learnability"
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault(
        "TABPFN_MODEL_CACHE_DIR", str((args.output / "model_cache").resolve())
    )
    os.environ.setdefault(
        "SKB_DATA_DIRECTORY", str((args.output / "model_cache" / "skrub").resolve())
    )
    os.environ.setdefault(
        "HF_HOME", str((args.output / "model_cache" / "huggingface").resolve())
    )
    os.environ.setdefault(
        "MPLCONFIGDIR", str((args.output / "model_cache" / "matplotlib").resolve())
    )
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    paths = [
        ROOT / "data/dataforNewVersion/production_analysis.csv",
        ROOT / "reports/data_preparation/production_analysis_split_manifest.csv",
    ]
    data, audit = datasets(pd.read_csv(paths[0]), pd.read_csv(paths[1]))
    report = {
        "evaluation": "validation_only_test_not_scored",
        "seed": 0,
        "device": args.device,
        "sources": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        "versions": {
            p: version(p)
            for p in ["pandas", "numpy", "scikit-learn"]
            + (["tabpfn", "torch"] if args.tabpfn else [])
        },
        "limitations": [
            "Conditional destination is taken from retrospective reports; its preassignment at prediction time is not verified.",
            "Machine gaps include waiting and reporting effects, not certified transport time.",
            "Whole-case span is observed event-log span, not certified delivery time.",
            "Small validation cohorts and prior descriptive inspection limit confidence.",
            "No final test score, solver integration or operational approval.",
        ],
        "tasks": {},
    }
    for name, dataset in data.items():
        print(
            f"Running {name}: {len(dataset[0])} train, {len(dataset[1])} validation",
            flush=True,
        )
        report["tasks"][name] = run_task(
            name, dataset, args.tabpfn, args.device, args.output
        )
        (args.output / "validation_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(report["tasks"][name]["validation_scores"], indent=2), flush=True
        )
    # Source audit counts are descriptive; no test predictions are calculated.
    report["raw_case_count"] = audit["case_count"]
    report["runner_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report["checkpoint_files"] = [
        {
            "name": p.name,
            "bytes": p.stat().st_size,
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        }
        for p in sorted((args.output / "model_cache").rglob("*.ckpt"))
    ]
    (args.output / "validation_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()

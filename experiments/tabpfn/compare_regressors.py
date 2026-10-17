"""Fixed-budget exploratory comparison; final test is never scored."""

import argparse
import hashlib
import json
import os
import time
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd

from experiments.tabpfn.learnability import (
    EXPERIMENT,
    ROOT,
    datasets,
    improvement_interval,
    score,
)

CONFIG = {
    "quantile_linear": {"quantile": 0.5, "alpha": 0.1, "solver": "highs"},
    "gradient_boosting_mae": {
        "loss": "absolute_error",
        "n_estimators": 100,
        "learning_rate": 0.05,
        "max_depth": 2,
        "min_samples_leaf": 5,
        "random_state": 0,
    },
    "catboost_mae": {
        "iterations": 200,
        "depth": 3,
        "learning_rate": 0.03,
        "l2_leaf_reg": 10,
        "loss_function": "MAE",
        "boosting_type": "Ordered",
        "random_seed": 0,
        "thread_count": 1,
        "verbose": False,
        "allow_writing_files": False,
    },
}


def verified_previous_predictions(path, frame, features):
    """Refuse stale or misaligned stored real-model predictions."""
    old = pd.read_csv(path)
    expected = frame[["case", "y"] + features].reset_index(drop=True)
    pd.testing.assert_frame_equal(
        old[["case", "y"] + features],
        expected,
        check_dtype=False,
        check_exact=False,
        rtol=1e-12,
        atol=1e-9,
    )
    return {
        model: old[model].to_numpy(dtype=float)
        for model in ("tabpfn_v2", "extra_trees")
    }


def compare_task(name, data, output, previous):
    from catboost import CatBoostRegressor
    from sklearn.compose import ColumnTransformer
    from sklearn.ensemble import GradientBoostingRegressor
    from sklearn.linear_model import QuantileRegressor
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    train, valid, features, categories, keys = data
    x, xv, y = train[features].copy(), valid[features].copy(), train.y.to_numpy()
    global_median = float(np.median(y))
    grouped = train.groupby(keys).y.median().to_dict()
    key_values = [
        tuple(row) if len(keys) > 1 else row[0]
        for row in valid[keys].itertuples(index=False, name=None)
    ]
    predictions = {
        "global_median": np.full(len(valid), global_median),
        "group_median": np.array(
            [grouped.get(key, global_median) for key in key_values]
        ),
    }
    numeric = [c for c in features if c not in categories]

    def preprocess(scale=False):
        return ColumnTransformer(
            [
                (
                    "cat",
                    OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                    categories,
                ),
                ("numeric", StandardScaler() if scale else "passthrough", numeric),
            ]
        )

    estimators = {
        "quantile_linear": make_pipeline(
            preprocess(True), QuantileRegressor(**CONFIG["quantile_linear"])
        ),
        "gradient_boosting_mae": make_pipeline(
            preprocess(), GradientBoostingRegressor(**CONFIG["gradient_boosting_mae"])
        ),
        "catboost_mae": CatBoostRegressor(
            cat_features=categories, **CONFIG["catboost_mae"]
        ),
    }
    result = {
        "features": features,
        "train_rows": len(train),
        "train_cases": int(train.case.nunique()),
        "validation_rows": len(valid),
        "validation_cases": int(valid.case.nunique()),
        "statuses": {},
        "runtime_seconds": {},
        "unseen_category_rows": {c: int((~xv[c].isin(x[c])).sum()) for c in categories},
    }
    for model, estimator in estimators.items():
        started = time.monotonic()
        try:
            estimator.fit(x, y)  # no eval_set, early stopping or validation tuning
            prediction = np.maximum(0, np.asarray(estimator.predict(xv), dtype=float))
            score(valid, prediction)  # reject NaNs before adding a reported result
            predictions[model] = prediction
            result["statuses"][model] = "real_fit_predict_completed"
        except Exception as exc:
            result["statuses"][model] = {
                "error_type": type(exc).__name__,
                "message": str(exc)[:1000],
            }
        result["runtime_seconds"][model] = time.monotonic() - started
    if previous is not None:
        predictions.update(verified_previous_predictions(previous, valid, features))
        result["previous_predictions_sha256"] = hashlib.sha256(
            previous.read_bytes()
        ).hexdigest()
        result["previous_models_status"] = (
            "stored_real_predictions_identity_checked_not_refitted"
        )
    result["validation_scores"] = {
        model: score(valid, p) for model, p in predictions.items()
    }
    result["paired_improvement_over_global_median"] = {
        model: improvement_interval(valid, predictions["global_median"], p)
        for model, p in predictions.items()
        if model != "global_median"
    }
    result["paired_improvement_over_group_median"] = {
        model: improvement_interval(valid, predictions["group_median"], p)
        for model, p in predictions.items()
        if model not in ("global_median", "group_median")
    }
    exported = valid[["case", "y"] + features].copy()
    for model, p in predictions.items():
        exported[model] = p
    exported.to_csv(output / f"{name}_validation_predictions.csv", index=False)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=EXPERIMENT / "results" / "regressor_comparison"
    )
    parser.add_argument(
        "--previous", type=Path, default=EXPERIMENT / "results" / "learnability"
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault(
        "MPLCONFIGDIR",
        str(
            (
                EXPERIMENT / "results" / "learnability" / "model_cache" / "matplotlib"
            ).resolve()
        ),
    )
    paths = [
        ROOT / "data/dataforNewVersion/production_analysis.csv",
        ROOT / "reports/data_preparation/production_analysis_split_manifest.csv",
    ]
    sources = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    prior = json.loads((args.previous / "validation_report.json").read_text())
    if prior["sources"] != sources:
        raise ValueError("Sources changed since prior TabPFN run; do not mix reports")
    tasks, _ = datasets(pd.read_csv(paths[0]), pd.read_csv(paths[1]))
    report = {
        "evaluation": "exploratory_reused_validation_final_test_not_scored",
        "sources": sources,
        "model_config": CONFIG,
        "versions": {
            p: version(p) for p in ("numpy", "pandas", "scikit-learn", "catboost")
        },
        "protocol": [
            "One fixed config per model, chosen before running; no grid search.",
            "Train-only preprocessing; fixed case-disjoint chronological split.",
            "Same validation previously inspected; exploratory gains require untouched test confirmation.",
            "All predictions clipped at zero; no target trimming.",
            "Train row weights equal; primary gap evaluation case weights equal.",
            "Conditional destination preassignment and physical target semantics are not verified.",
        ],
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "dataset_builder_sha256": hashlib.sha256(
            (EXPERIMENT / "learnability.py").read_bytes()
        ).hexdigest(),
        "tasks": {},
    }
    (args.output / "fixed_protocol.json").write_text(
        json.dumps(
            {k: v for k, v in report.items() if k != "tasks"},
            ensure_ascii=False,
            indent=2,
        )
    )
    for name, data in tasks.items():
        print(f"Running {name}", flush=True)
        report["tasks"][name] = compare_task(
            name,
            data,
            args.output,
            args.previous / f"{name}_validation_predictions.csv",
        )
        (args.output / "validation_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(report["tasks"][name]["validation_scores"], indent=2), flush=True
        )


if __name__ == "__main__":
    main()

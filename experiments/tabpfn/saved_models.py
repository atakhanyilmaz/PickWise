"""Persist/load trusted local experiments, including explicit all-data refits."""

import argparse
import hashlib
import json
import os
import time
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd

from experiments.tabpfn.compare_regressors import CONFIG
from experiments.tabpfn.learnability import (
    EXPERIMENT,
    ROOT,
    datasets,
    score,
    target_tables,
)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def artifact(path):
    return {"filename": path.name, "bytes": path.stat().st_size, "sha256": digest(path)}


def setup_cache():
    cache = EXPERIMENT / "results" / "learnability" / "model_cache"
    for key, sub in (
        ("TABPFN_MODEL_CACHE_DIR", ""),
        ("SKB_DATA_DIRECTORY", "skrub"),
        ("HF_HOME", "huggingface"),
        ("MPLCONFIGDIR", "matplotlib"),
    ):
        os.environ.setdefault(key, str((cache / sub).resolve()))
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    return cache


def estimators(features, categories):
    from catboost import CatBoostRegressor
    from sklearn.compose import ColumnTransformer
    from sklearn.ensemble import ExtraTreesRegressor, GradientBoostingRegressor
    from sklearn.linear_model import QuantileRegressor
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    numeric = [c for c in features if c not in categories]

    def prep(scale=False):
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

    return {
        "quantile_linear": make_pipeline(
            prep(True), QuantileRegressor(**CONFIG["quantile_linear"])
        ),
        "gradient_boosting_mae": make_pipeline(
            prep(), GradientBoostingRegressor(**CONFIG["gradient_boosting_mae"])
        ),
        "catboost_mae": CatBoostRegressor(
            cat_features=categories, **CONFIG["catboost_mae"]
        ),
        "extra_trees": make_pipeline(
            prep(),
            ExtraTreesRegressor(
                n_estimators=100,
                max_depth=4,
                min_samples_leaf=3,
                random_state=0,
                n_jobs=1,
            ),
        ),
    }


def verify_files(directory, files):
    directory = Path(directory).resolve()
    for item in files:
        path = (directory / item["filename"]).resolve()
        if path.parent != directory or digest(path) != item["sha256"]:
            raise ValueError("Model artifact checksum/path mismatch")


def predict_saved(directory, model_name, frame):
    """Only use with trusted artifacts created by this runner (joblib loads code)."""
    import joblib

    setup_cache()
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    features = manifest["features"]
    if list(frame.columns) != features or frame.isna().any().any():
        raise ValueError(f"Expected nonmissing features in this order: {features}")
    if model_name in ("global_median", "group_median"):
        verify_files(directory, [manifest["baselines_file"]])
        baseline = json.loads((directory / "baselines.json").read_text())
        if model_name == "global_median":
            return np.full(len(frame), baseline["global_median"])
        groups = {tuple(r["key"]): r["median"] for r in baseline["groups"]}
        return np.array(
            [
                groups.get(tuple(row), baseline["global_median"])
                for row in frame[baseline["keys"]].itertuples(index=False, name=None)
            ]
        )
    item = manifest["models"][model_name]
    verify_files(directory, item["files"])
    path = directory / item["files"][0]["filename"]
    if model_name == "catboost_mae":
        from catboost import CatBoostRegressor

        model = CatBoostRegressor()
        model.load_model(str(path))
        prediction = model.predict(frame)
    elif model_name == "tabpfn_v2":
        from tabpfn import TabPFNRegressor

        weight = Path(manifest["foundation_checkpoint"]["path"])
        if (
            not weight.exists()
            or digest(weight) != manifest["foundation_checkpoint"]["sha256"]
        ):
            raise ValueError("Required foundation checkpoint is missing/changed")
        encoder = joblib.load(directory / item["files"][1]["filename"])
        data = frame.copy()
        data[manifest["categories"]] = encoder.transform(frame[manifest["categories"]])
        model = TabPFNRegressor.load_from_fit_state(path, device="cpu")
        prediction = model.predict(data.to_numpy(dtype=float))
    else:
        model = joblib.load(path)
        prediction = model.predict(frame)
    prediction = np.maximum(0, np.asarray(prediction, dtype=float))
    if prediction.shape != (len(frame),) or not np.isfinite(prediction).all():
        raise ValueError("Invalid prediction from saved model")
    return prediction


def save_scope(
    task,
    scope,
    train,
    valid,
    features,
    categories,
    keys,
    directory,
    source,
    models=None,
):
    import joblib

    selected = set(
        models
        or [
            "quantile_linear",
            "gradient_boosting_mae",
            "catboost_mae",
            "extra_trees",
            "tabpfn_v2",
        ]
    )

    directory.mkdir(parents=True, exist_ok=False)
    train.to_csv(directory / "training_rows.csv", index=False)
    x, y = train[features].copy(), train.y.to_numpy()
    probe = (valid if valid is not None else train.iloc[:5])[features].copy()
    (directory / "example_input.json").write_text(
        probe.iloc[:1].to_json(orient="records", force_ascii=False, indent=2),
        encoding="utf-8",
    )
    metadata = {
        "task": task,
        "scope": scope,
        "source_csv": str(source.resolve()),
        "source_sha256": digest(source),
        "target_unit": "minutes",
        "features": features,
        "categories": categories,
        "train_rows": len(train),
        "train_cases": int(train.case.nunique()),
        "train_counts_by_original_split": train.split.value_counts().to_dict(),
        "independent_performance_established": False,
        "includes_former_holdout": scope == "all_data_refit_unvalidated",
        "model_config": CONFIG,
        "models": {},
        "validation_scores": {},
        "training_table": artifact(directory / "training_rows.csv"),
        "versions": {
            p: version(p)
            for p in (
                "tabpfn",
                "torch",
                "catboost",
                "scikit-learn",
                "joblib",
                "pandas",
                "numpy",
            )
        },
    }
    global_median = float(np.median(y))
    medians = train.groupby(keys).y.median()
    baseline = {
        "global_median": global_median,
        "keys": keys,
        "groups": [
            {"key": list(k) if isinstance(k, tuple) else [k], "median": float(v)}
            for k, v in medians.items()
        ],
    }
    (directory / "baselines.json").write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2)
    )
    metadata["baselines_file"] = artifact(directory / "baselines.json")
    for name, model in estimators(features, categories).items():
        if name not in selected:
            continue
        started = time.monotonic()
        model.fit(x, y)
        expected = np.maximum(0, np.asarray(model.predict(probe)))
        fit_predict_seconds = time.monotonic() - started
        if name == "catboost_mae":
            path = directory / f"{name}.cbm"
            model.save_model(str(path))
        else:
            path = directory / f"{name}.joblib"
            joblib.dump(model, path)
        metadata["models"][name] = {
            "files": [artifact(path)],
            "fit_predict_seconds": fit_predict_seconds,
        }
        (directory / "manifest.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2)
        )
        restored = predict_saved(directory, name, probe)
        np.testing.assert_allclose(restored, expected, rtol=1e-8, atol=1e-6)
        metadata["models"][name]["reload_predictions_match"] = True
        if valid is not None:
            metadata["validation_scores"][name] = score(valid, restored)
        print(
            f"{task}/{scope}/{name}: saved + reload verified ({fit_predict_seconds:.3f}s)",
            flush=True,
        )
    if valid is not None:
        for baseline_name in ("global_median", "group_median"):
            metadata["validation_scores"][baseline_name] = score(
                valid, predict_saved(directory, baseline_name, probe)
            )
    if "tabpfn_v2" not in selected:
        (directory / "manifest.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2)
        )
        return metadata
    from sklearn.preprocessing import OrdinalEncoder
    from tabpfn import TabPFNRegressor

    checkpoint = setup_cache() / "tabpfn-v2-regressor.ckpt"
    if not checkpoint.is_file():
        raise FileNotFoundError(
            "Run the explicit v2 experiment once to download its checkpoint"
        )
    metadata["foundation_checkpoint"] = {
        "path": str(checkpoint.resolve()),
        **artifact(checkpoint),
    }
    encoder = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)
    encoded = x.copy()
    encoded[categories] = encoder.fit_transform(x[categories])
    encoded_probe = probe.copy()
    encoded_probe[categories] = encoder.transform(probe[categories])
    model = TabPFNRegressor(
        model_path=str(checkpoint.resolve()),
        device="cpu",
        random_state=0,
        n_estimators=4,
        categorical_features_indices=[features.index(c) for c in categories],
    )
    started = time.monotonic()
    model.fit(encoded.to_numpy(dtype=float), y)
    expected = np.maximum(
        0, np.asarray(model.predict(encoded_probe.to_numpy(dtype=float)))
    )
    fit_predict_seconds = time.monotonic() - started
    path = directory / "tabpfn_v2.tabpfn_fit"
    model.save_fit_state(path)
    encoder_path = directory / "tabpfn_encoder.joblib"
    joblib.dump(encoder, encoder_path)
    metadata["models"]["tabpfn_v2"] = {
        "files": [artifact(path), artifact(encoder_path)],
        "fit_predict_seconds": fit_predict_seconds,
        "weights_fine_tuned": False,
        "n_estimators": 4,
    }
    (directory / "manifest.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2)
    )
    restored = predict_saved(directory, "tabpfn_v2", probe)
    np.testing.assert_allclose(restored, expected, rtol=1e-6, atol=1e-3)
    metadata["models"]["tabpfn_v2"]["reload_predictions_match"] = True
    if valid is not None:
        metadata["validation_scores"]["tabpfn_v2"] = score(valid, restored)
        for baseline_name in ("global_median", "group_median"):
            metadata["validation_scores"][baseline_name] = score(
                valid, predict_saved(directory, baseline_name, probe)
            )
    (directory / "manifest.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2)
    )
    print(
        f"{task}/{scope}/tabpfn_v2: fit state + encoder saved and reload verified ({fit_predict_seconds:.3f}s)",
        flush=True,
    )
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--csv",
        type=Path,
        default=ROOT / "data/dataforNewVersion/production_analysis.csv",
    )
    parser.add_argument(
        "--output", type=Path, default=EXPERIMENT / "results" / "saved_models"
    )
    parser.add_argument("--predict-dir", type=Path)
    parser.add_argument("--model")
    parser.add_argument("--input", type=Path)
    parser.add_argument(
        "--models",
        nargs="+",
        choices=[
            "quantile_linear",
            "gradient_boosting_mae",
            "catboost_mae",
            "extra_trees",
            "tabpfn_v2",
        ],
    )
    args = parser.parse_args()
    setup_cache()
    if args.predict_dir:
        if not args.model or not args.input:
            parser.error("Prediction needs --model and --input JSON list")
        prediction = predict_saved(
            args.predict_dir,
            args.model,
            pd.DataFrame(json.loads(args.input.read_text())),
        )
        print(
            json.dumps(
                {"unit": "minutes", "predictions": prediction.tolist()}, indent=2
            )
        )
        return
    raw = pd.read_csv(args.csv)
    manifest_path = (
        ROOT / "reports/data_preparation/production_analysis_split_manifest.csv"
    )
    manifest = pd.read_csv(manifest_path)
    evaluated, _ = datasets(raw, manifest)
    tables, _, _ = target_tables(raw, manifest)
    if args.output.exists():
        raise FileExistsError(
            "Choose a new output directory; saved models are never overwritten"
        )
    args.output.mkdir(parents=True)
    summary = {
        "source_csv": str(args.csv.resolve()),
        "source_sha256": digest(args.csv),
        "raw_rows": len(raw),
        "manifest_sha256": digest(manifest_path),
        "tasks": {},
        "warning": "All-data refits include former test/quarantine cases and have no independent performance estimate. Experimental only.",
    }
    for task, (train, valid, features, categories, keys) in evaluated.items():
        summary["tasks"][task] = {}
        summary["tasks"][task]["evaluated_train_only"] = save_scope(
            task,
            "evaluated_train_only",
            train,
            valid,
            features,
            categories,
            keys,
            args.output / task / "evaluated_train_only",
            args.csv,
            args.models,
        )
        full = tables[task][0]
        summary["tasks"][task]["all_data_refit_unvalidated"] = save_scope(
            task,
            "all_data_refit_unvalidated",
            full,
            None,
            features,
            categories,
            keys,
            args.output / task / "all_data_refit_unvalidated",
            args.csv,
            args.models,
        )
        (args.output / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    main()

"""Compare compact regressors on Production Analysis and CNC Changeover splits.

Run with:
  python -m ml_experiments.compare_duration_models --dataset production
  python -m ml_experiments.compare_duration_models --dataset cnc
"""
from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path

import inspect
import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import (
    ExtraTreesRegressor,
    GradientBoostingRegressor,
    HistGradientBoostingRegressor,
    RandomForestRegressor,
)
from sklearn.linear_model import ElasticNet, HuberRegressor, Ridge
from sklearn.metrics import median_absolute_error, r2_score
from sklearn.neighbors import KNeighborsRegressor
from sklearn.neural_network import MLPRegressor

from ml_experiments.duration_features import (
    DATA,
    ROOT,
    SEED,
    Dataset,
    artifact_path,
    categorical,
    encoder_for,
    group_weights,
    is_numeric,
    load_cnc,
    load_production,
    production_engineering,
    sha256,
)

MODEL_ORDER = [
    "median",
    "ridge",
    "elastic_net",
    "huber",
    "knn",
    "random_forest",
    "extra_trees",
    "gradient_boosting",
    "hist_gradient_boosting",
    "mlp",
    "lightgbm",
    "xgboost",
    "catboost",
]

MODEL_DISPLAY_NAMES = {
    "median": "Median (Baz)",
    "ridge": "Ridge (L2)",
    "elastic_net": "ElasticNet",
    "huber": "Huber (Robüst)",
    "knn": "KNN Regresyon",
    "random_forest": "Random Forest",
    "extra_trees": "Extra Trees",
    "gradient_boosting": "Gradient Boosting",
    "hist_gradient_boosting": "HistGradientBoosting",
    "mlp": "MLP (Sinir Ağı)",
    "lightgbm": "LightGBM",
    "xgboost": "XGBoost",
    "catboost": "CatBoost",
}

CNC_TRANSITION_CONTEXT = [
    "transition_from_product",
    "transition_to_product",
    "elapsed_changeover_time_min",
]


@dataclass
class Candidate:
    name: str
    parameters: dict
    model: object
    encoder: object | None = None
    activity_medians: dict | None = None
    transition_medians: dict | None = None
    global_median: float | None = None
    categorical_columns: list[str] | None = None

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        if self.name == "median":
            if self.transition_medians is not None:
                totals = [
                    self.transition_medians.get(
                        (
                            str(row.transition_from_product),
                            str(row.transition_to_product),
                        ),
                        self.global_median,
                    )
                    for row in frame[CNC_TRANSITION_CONTEXT].itertuples()
                ]
                elapsed = pd.to_numeric(
                    frame["elapsed_changeover_time_min"], errors="raise"
                ).to_numpy(dtype=float)
                return np.maximum(0.0, np.asarray(totals, dtype=float) - elapsed)
            values = (
                frame["Activity"].map(self.activity_medians).fillna(self.global_median)
            )
            return values.to_numpy(dtype=float)
        if self.name == "catboost":
            matrix = catboost_frame(frame, self.categorical_columns or [])
        else:
            matrix = self.encoder.transform(frame)
        return np.maximum(0.0, np.asarray(self.model.predict(matrix), dtype=float))


def catboost_frame(frame: pd.DataFrame, categorical_columns: list[str]) -> pd.DataFrame:
    result = frame.copy()
    for column in categorical_columns:
        result[column] = categorical(result[column])
    return result


def prepare_features(dataset: Dataset) -> pd.DataFrame:
    if dataset.name == "production_analysis":
        return production_engineering(dataset.features)
    return dataset.features.copy()


def load_cnc_benchmark_dataset(
    representation: str = "engineered", data_dir: Path = DATA
) -> Dataset:
    """Load audited CNC changeover data with causal window or PCA features plus transition context."""
    base = load_cnc(data_dir)
    if representation == "raw_audited":
        return base
    bi_pre = data_dir / "biPre"
    kind_map = {
        "selected": "selected",
        "engineered": "engineered",
        "pca": "extracted",
    }
    if representation not in kind_map:
        raise ValueError(f"Unsupported CNC representation: {representation}")
    matrix_path = artifact_path("cnc_changeover", kind_map[representation], bi_pre)
    if not matrix_path.exists():
        return base
    exported = pd.read_csv(matrix_path, low_memory=False)
    meta_cols = ["source_row", "group_id", "time", "split"]
    feature_cols = [
        c for c in exported.columns if c not in set(meta_cols) | {base.target}
    ]
    aligned_index = pd.Index(base.metadata["time"]).get_indexer(exported["time"])
    if (aligned_index < 0).any():
        raise ValueError("Exported CNC matrix timestamps do not align with audited data")
    features = exported[feature_cols].reset_index(drop=True)
    for col in CNC_TRANSITION_CONTEXT:
        if col not in features.columns and col in base.features.columns:
            features[col] = (
                base.features[col].iloc[aligned_index].reset_index(drop=True)
            )
    meta = exported[meta_cols].reset_index(drop=True)
    target = pd.Series(
        exported[base.target].to_numpy(dtype=float), name=base.target
    )
    notes = {
        **base.notes,
        "representation": representation,
        "matrix_path": str(
            matrix_path.relative_to(ROOT)
            if matrix_path.is_relative_to(ROOT)
            else matrix_path
        ),
    }
    return Dataset(
        "cnc_changeover",
        base.target,
        features,
        meta,
        target,
        [*base.paths, matrix_path],
        notes,
    )


def regression_metrics(actual, predicted, groups) -> dict:
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    if actual.shape != predicted.shape or not np.isfinite(predicted).all():
        raise ValueError("Invalid model predictions")
    absolute = np.abs(actual - predicted)
    grouped = pd.DataFrame({"group": np.asarray(groups), "error": absolute})
    per_group = grouped.groupby("group").error.mean()
    return {
        "rows": int(len(actual)),
        "groups": int(len(per_group)),
        "row_mae_min": float(absolute.mean()),
        "group_macro_mae_min": float(per_group.mean()),
        "rmse_min": float(math.sqrt(np.mean((actual - predicted) ** 2))),
        "median_absolute_error_min": float(median_absolute_error(actual, predicted)),
        "p90_absolute_error_min": float(np.quantile(absolute, 0.90)),
        "max_predicted_min": float(np.max(predicted)),
        "r2": float(r2_score(actual, predicted)),
        "per_group_mae_min": {
            str(key): float(value) for key, value in per_group.items()
        },
    }


def timed_validation(
    candidate: Candidate, frame, target, groups
) -> tuple[dict, np.ndarray]:
    started = time.perf_counter()
    predicted = candidate.predict(frame)
    elapsed = time.perf_counter() - started
    metrics = regression_metrics(target, predicted, groups)
    metrics["prediction_seconds"] = float(elapsed)
    metrics["prediction_ms_per_row"] = float(elapsed * 1000 / len(frame))
    return metrics, predicted


def fit_median(
    frame: pd.DataFrame, target: pd.Series, groups: pd.Series | None = None
) -> tuple[Candidate, float]:
    started = time.perf_counter()
    if set(CNC_TRANSITION_CONTEXT) <= set(frame.columns):
        history = frame[CNC_TRANSITION_CONTEXT].copy()
        history["total"] = (
            pd.to_numeric(target, errors="raise").to_numpy(dtype=float)
            + pd.to_numeric(
                history["elapsed_changeover_time_min"], errors="raise"
            ).to_numpy(dtype=float)
        )
        history["group"] = (
            np.asarray(groups) if groups is not None else np.arange(len(frame))
        )
        sessions = history.groupby("group", sort=False).first()
        grouped = (
            sessions.groupby(["transition_from_product", "transition_to_product"])[
                "total"
            ]
            .median()
            .to_dict()
        )
        transition_medians = {
            (str(k[0]), str(k[1])): float(v) for k, v in grouped.items()
        }
        candidate = Candidate(
            name="median",
            parameters={"fallback": "session_transition_total_median_minus_elapsed"},
            model=None,
            transition_medians=transition_medians,
            global_median=float(sessions["total"].median()),
        )
        return candidate, time.perf_counter() - started

    history = pd.DataFrame({"activity": frame["Activity"], "target": target})
    candidate = Candidate(
        name="median",
        parameters={"fallback": "training_global_median"},
        model=None,
        activity_medians=history.groupby("activity").target.median().to_dict(),
        global_median=float(history.target.median()),
    )
    return candidate, time.perf_counter() - started


def fit_sklearn(
    name,
    estimator,
    parameters,
    train_frame,
    train_target,
    weights,
    *,
    encoded_cache: tuple[object, np.ndarray] | None = None,
):
    started = time.perf_counter()
    if encoded_cache is not None:
        encoder, matrix = encoded_cache
    else:
        encoder = encoder_for(train_frame)
        matrix = encoder.fit_transform(train_frame)
    fit_params = inspect.signature(estimator.fit).parameters
    if "sample_weight" in fit_params:
        estimator.fit(matrix, train_target, sample_weight=weights)
    else:
        estimator.fit(matrix, train_target)
    return (
        Candidate(name, parameters, estimator, encoder=encoder),
        time.perf_counter() - started,
    )


def fit_lightgbm(
    parameters,
    train_frame,
    train_target,
    weights,
    *,
    encoded_cache: tuple[object, np.ndarray] | None = None,
):
    try:
        from lightgbm import LGBMRegressor
    except ImportError as error:  # pragma: no cover
        raise RuntimeError(
            "Install requirements-features.txt to run LightGBM"
        ) from error

    model = LGBMRegressor(
        objective=parameters["objective"],
        n_estimators=parameters.get("n_estimators", 250),
        max_depth=parameters["max_depth"],
        num_leaves=parameters["num_leaves"],
        learning_rate=parameters["learning_rate"],
        min_child_samples=parameters.get("min_child_samples", 10),
        subsample_for_bin=50000,
        random_state=SEED,
        n_jobs=1,
        deterministic=True,
        force_col_wise=True,
        verbose=-1,
    )
    return fit_sklearn(
        "lightgbm",
        model,
        parameters,
        train_frame,
        train_target,
        weights,
        encoded_cache=encoded_cache,
    )


def fit_xgboost(
    parameters,
    train_frame,
    train_target,
    weights,
    *,
    encoded_cache: tuple[object, np.ndarray] | None = None,
):
    try:
        from xgboost import XGBRegressor
    except ImportError as error:  # pragma: no cover
        raise RuntimeError(
            "Install requirements-features.txt to run XGBoost"
        ) from error

    model = XGBRegressor(
        objective=parameters["objective"],
        n_estimators=parameters.get("n_estimators", 250),
        max_depth=parameters["max_depth"],
        learning_rate=parameters["learning_rate"],
        reg_lambda=parameters.get("reg_lambda", 3.0),
        tree_method="hist",
        random_state=SEED,
        n_jobs=1,
        verbosity=0,
    )
    return fit_sklearn(
        "xgboost",
        model,
        parameters,
        train_frame,
        train_target,
        weights,
        encoded_cache=encoded_cache,
    )


def fit_catboost(
    parameters,
    train_frame,
    train_target,
    weights,
    validation_frame,
    validation_target,
):
    try:
        from catboost import CatBoostRegressor
    except ImportError as error:  # pragma: no cover - exercised by the real CLI environment
        raise RuntimeError(
            "Install requirements-features.txt to run CatBoost"
        ) from error

    categorical_columns = [
        column for column in train_frame if not is_numeric(train_frame[column])
    ]
    training = catboost_frame(train_frame, categorical_columns)
    validation = catboost_frame(validation_frame, categorical_columns)
    loss_fn = parameters.get("loss_function", "MAE")
    model = CatBoostRegressor(
        loss_function=loss_fn,
        eval_metric="MAE",
        random_seed=SEED,
        iterations=parameters.get("iterations", 1000),
        depth=parameters["depth"],
        learning_rate=parameters["learning_rate"],
        l2_leaf_reg=3,
        allow_writing_files=False,
        thread_count=1,
        verbose=False,
    )
    started = time.perf_counter()
    model.fit(
        training,
        train_target,
        sample_weight=weights,
        cat_features=categorical_columns,
        eval_set=(validation, validation_target),
        early_stopping_rounds=50,
        use_best_model=True,
    )
    fitted = dict(parameters)
    fitted["loss_function"] = loss_fn
    fitted["best_iteration"] = int(model.get_best_iteration())
    return (
        Candidate("catboost", fitted, model, categorical_columns=categorical_columns),
        time.perf_counter() - started,
    )


def choose_candidate(
    validation: dict[str, dict], minimum_improvement: float = 0.10
) -> tuple[str, dict]:
    scores = {
        name: result["metrics"]["group_macro_mae_min"]
        for name, result in validation.items()
    }
    best_score = min(scores.values())
    within_one_percent = {
        name for name, score in scores.items() if score <= best_score * 1.01
    }
    selected = next(name for name in MODEL_ORDER if name in within_one_percent)
    baseline = scores["median"]
    improvement = (baseline - scores[selected]) / baseline if baseline else 0.0
    if selected != "median" and improvement < minimum_improvement:
        selected = "median"
    return selected, {
        "primary_metric": "validation_group_macro_mae_min",
        "tie_rule": (
            "within 1 percent chooses simplest model in MODEL_ORDER: "
            + ", ".join(MODEL_ORDER)
        ),
        "minimum_improvement_over_median": float(minimum_improvement),
        "selected_improvement_over_median": float(
            (baseline - scores[selected]) / baseline if baseline else 0.0
        ),
    }


def comparison_plot(
    validation: dict[str, dict],
    holdout_actual: np.ndarray,
    holdout_predicted: np.ndarray,
    winner: str,
    output: Path,
    *,
    test_summary: dict[str, dict] | None = None,
    test_predictions_by_model: dict[str, np.ndarray] | None = None,
    dataset_name: str = "production_analysis",
):
    names = [name for name in MODEL_ORDER if name in validation]
    display_names = [MODEL_DISPLAY_NAMES.get(n, n) for n in names]
    y_pos = np.arange(len(names))

    val_group_mae = [validation[n]["metrics"]["group_macro_mae_min"] for n in names]
    val_row_mae = [validation[n]["metrics"]["row_mae_min"] for n in names]
    val_rmse = [validation[n]["metrics"]["rmse_min"] for n in names]
    val_medae = [validation[n]["metrics"]["median_absolute_error_min"] for n in names]
    val_p90 = [validation[n]["metrics"]["p90_absolute_error_min"] for n in names]
    val_r2 = [validation[n]["metrics"]["r2"] for n in names]

    figure, axes = plt.subplots(3, 2, figsize=(20, 15))
    figure.suptitle(
        f"Kapsamlı Süre Tahmin Modelleri Karşılaştırması ({dataset_name}) — {len(names)} Model | Seçilen: {MODEL_DISPLAY_NAMES.get(winner, winner)}",
        fontsize=15,
        fontweight="bold",
        y=0.992,
    )

    # Panel 1: Validation Group-Macro MAE & Row MAE
    ax0 = axes[0, 0]
    bar_h = 0.38
    b1 = ax0.barh(
        y_pos - bar_h / 2,
        val_group_mae,
        height=bar_h,
        color=["#d97706" if n == winner else "#1d4ed8" for n in names],
        label="Grup-Makro MAE (dk)",
    )
    b2 = ax0.barh(
        y_pos + bar_h / 2,
        val_row_mae,
        height=bar_h,
        color="#60a5fa",
        alpha=0.85,
        label="Satır MAE (dk)",
    )
    if "median" in validation:
        ax0.axvline(
            validation["median"]["metrics"]["group_macro_mae_min"],
            color="#dc2626",
            linestyle="--",
            linewidth=1.3,
            label="Medyan Baz",
        )
    ax0.set_yticks(y_pos, labels=display_names, fontsize=9.5)
    ax0.invert_yaxis()
    ax0.set_xlabel("Dakika (Düşük = Daha İyi)")
    ax0.set_title("1) Doğrulama (Validation) Grup-Makro MAE ve Satır MAE", fontweight="bold")
    ax0.grid(axis="x", linestyle=":", alpha=0.5)
    ax0.legend(loc="lower right", fontsize=8.5)
    max_val_mae = max(max(val_group_mae), max(val_row_mae), 1.0)
    ax0.set_xlim(0, max_val_mae * 1.18)
    for rect in b1:
        w = rect.get_width()
        ax0.text(
            w + max_val_mae * 0.01,
            rect.get_y() + rect.get_height() / 2,
            f"{w:.1f}",
            va="center",
            fontsize=8,
            fontweight="bold",
        )
    for rect in b2:
        w = rect.get_width()
        ax0.text(
            w + max_val_mae * 0.01,
            rect.get_y() + rect.get_height() / 2,
            f"{w:.1f}",
            va="center",
            fontsize=7.5,
            color="#1e3a8a",
        )

    # Panel 2: Test Group-Macro MAE & Row MAE across all models
    ax1 = axes[0, 1]
    if test_summary:
        test_group_mae = [test_summary[n]["group_macro_mae_min"] for n in names]
        test_row_mae = [test_summary[n]["row_mae_min"] for n in names]
    else:
        test_group_mae = val_group_mae
        test_row_mae = val_row_mae
    tb1 = ax1.barh(
        y_pos - bar_h / 2,
        test_group_mae,
        height=bar_h,
        color=["#15803d" if n == winner else "#0f766e" for n in names],
        label="Test Grup-Makro MAE (dk)",
    )
    tb2 = ax1.barh(
        y_pos + bar_h / 2,
        test_row_mae,
        height=bar_h,
        color="#5eead4",
        alpha=0.85,
        label="Test Satır MAE (dk)",
    )
    if test_summary and "median" in test_summary:
        ax1.axvline(
            test_summary["median"]["group_macro_mae_min"],
            color="#dc2626",
            linestyle="--",
            linewidth=1.3,
            label="Test Medyan Baz",
        )
    ax1.set_yticks(y_pos, labels=display_names, fontsize=9.5)
    ax1.invert_yaxis()
    ax1.set_xlabel("Dakika (Düşük = Daha İyi)")
    ax1.set_title("2) Test Bölümü Grup-Makro MAE ve Satır MAE (Tüm Modeller)", fontweight="bold")
    ax1.grid(axis="x", linestyle=":", alpha=0.5)
    ax1.legend(loc="lower right", fontsize=8.5)
    max_test_mae = max(max(test_group_mae), max(test_row_mae), 1.0)
    ax1.set_xlim(0, max_test_mae * 1.18)
    for rect in tb1:
        w = rect.get_width()
        ax1.text(
            w + max_test_mae * 0.01,
            rect.get_y() + rect.get_height() / 2,
            f"{w:.1f}",
            va="center",
            fontsize=8,
            fontweight="bold",
        )
    for rect in tb2:
        w = rect.get_width()
        ax1.text(
            w + max_test_mae * 0.01,
            rect.get_y() + rect.get_height() / 2,
            f"{w:.1f}",
            va="center",
            fontsize=7.5,
            color="#115e59",
        )

    # Panel 3: RMSE, MedAE & P90 Error Breakdown (Validation)
    ax2 = axes[1, 0]
    w3 = 0.26
    ax2.barh(y_pos - w3, val_medae, height=w3, color="#10b981", label="Medyan Mutlak Hata (MedAE)")
    ax2.barh(y_pos, val_rmse, height=w3, color="#f59e0b", label="Kök Ortalama Kare Hata (RMSE)")
    ax2.barh(y_pos + w3, val_p90, height=w3, color="#ef4444", label="P90 Mutlak Hata (%90 Dilim)")
    ax2.set_yticks(y_pos, labels=display_names, fontsize=9.5)
    ax2.invert_yaxis()
    ax2.set_xlabel("Dakika (Düşük = Daha İyi)")
    ax2.set_title("3) Doğrulama Hata Dağılımı: MedAE, RMSE ve P90 Hata", fontweight="bold")
    ax2.grid(axis="x", linestyle=":", alpha=0.5)
    ax2.legend(loc="lower right", fontsize=8.5)

    # Panel 4: Validation & Test R2 Score + Max Prediction Range
    ax3 = axes[1, 1]
    test_r2 = (
        [test_summary[n]["r2"] for n in names]
        if test_summary
        else val_r2
    )
    ax3.barh(
        y_pos - bar_h / 2,
        val_r2,
        height=bar_h,
        color="#6366f1",
        label="Doğrulama R²",
    )
    ax3.barh(
        y_pos + bar_h / 2,
        test_r2,
        height=bar_h,
        color="#a855f7",
        alpha=0.85,
        label="Test R²",
    )
    ax3.axvline(0.0, color="black", linewidth=0.9, linestyle="-")
    ax3.set_yticks(y_pos, labels=display_names, fontsize=9.5)
    ax3.invert_yaxis()
    ax3.set_xlabel("R² Açıklanan Varyans Skoru (Yüksek = Daha İyi)")
    ax3.set_title("4) Doğrulama ve Test R² Skoru Karşılaştırması", fontweight="bold")
    ax3.grid(axis="x", linestyle=":", alpha=0.5)
    ax3.legend(loc="lower right", fontsize=8.5)
    for idx, (vr, tr) in enumerate(zip(val_r2, test_r2)):
        ax3.text(
            max(vr, tr, 0.0) + 0.01,
            idx,
            f"V:{vr:.2f} | T:{tr:.2f}",
            va="center",
            fontsize=7.8,
        )
    min_r2 = min(min(val_r2), min(test_r2), -0.15)
    max_r2 = max(max(val_r2), max(test_r2), 0.35)
    ax3.set_xlim(min_r2 - 0.05, max_r2 + 0.25)

    # Panel 5: Test Scatter — Multi-Model Actual vs Predicted (showing both MAE and L2/Tree ranges)
    ax4 = axes[2, 0]
    scatter_models = []
    for candidate_name, color, marker in [
        (winner, "#dc2626", "o"),
        ("random_forest", "#2563eb", "^"),
        ("extra_trees", "#059669", "s"),
        ("xgboost", "#7c3aed", "D"),
        ("lightgbm", "#d97706", "P"),
        ("ridge", "#0891b2", "x"),
    ]:
        if (
            test_predictions_by_model
            and candidate_name in test_predictions_by_model
            and candidate_name not in [m[0] for m in scatter_models]
        ):
            scatter_models.append((candidate_name, color, marker))
        if len(scatter_models) >= 4:
            break

    max_pred_seen = float(np.max(holdout_predicted)) if len(holdout_predicted) else 1.0
    if scatter_models and test_predictions_by_model:
        for m_name, color, marker in scatter_models:
            preds = test_predictions_by_model[m_name]
            max_pred_seen = max(max_pred_seen, float(np.max(preds)))
            ax4.scatter(
                holdout_actual,
                preds,
                alpha=0.55,
                s=26,
                color=color,
                marker=marker,
                label=f"{MODEL_DISPLAY_NAMES.get(m_name, m_name)} (maks={np.max(preds):.0f} dk)",
            )
    else:
        ax4.scatter(
            holdout_actual,
            holdout_predicted,
            alpha=0.65,
            s=28,
            color="#dc2626",
            label=f"{MODEL_DISPLAY_NAMES.get(winner, winner)}",
        )
    limit = max(float(np.max(holdout_actual)), max_pred_seen, 1.0)
    ax4.plot([0, limit], [0, limit], linestyle="--", color="black", linewidth=1.2, label="İdeal (y = x)")
    ax4.set_title(
        "5) Test: Gerçek vs Tahmin Dağılımı (Çoklu Model & Tahmin Tavanı)",
        fontweight="bold",
    )
    ax4.set_xlabel("Gerçek Süre (Dakika)")
    ax4.set_ylabel("Tahmin Edilen Süre (Dakika)")
    ax4.grid(True, linestyle=":", alpha=0.5)
    ax4.legend(loc="upper left", fontsize=8.5)

    # Panel 6: Boxplot of Absolute Errors on Test Split across all models
    ax5 = axes[2, 1]
    if test_predictions_by_model:
        abs_error_series = [
            np.abs(holdout_actual - test_predictions_by_model[n]) for n in names if n in test_predictions_by_model
        ]
        box_labels = [MODEL_DISPLAY_NAMES.get(n, n) for n in names if n in test_predictions_by_model]
    else:
        abs_error_series = [np.abs(holdout_actual - holdout_predicted)]
        box_labels = [MODEL_DISPLAY_NAMES.get(winner, winner)]
    bp = ax5.boxplot(
        abs_error_series,
        vert=False,
        patch_artist=True,
        showfliers=False,
        tick_labels=box_labels,
    )
    for patch, n in zip(bp["boxes"], names):
        patch.set_facecolor("#fde68a" if n == winner else "#bfdbfe")
        patch.set_edgecolor("#1e3a8a")
    ax5.invert_yaxis()
    ax5.set_xlabel("Mutlak Hata |Gerçek - Tahmin| (Dakika, Aykırı Değerler Hariç IQR)")
    ax5.set_title("6) Test Bölümü Model Bazlı Mutlak Hata Kutu Grafiği (Boxplot)", fontweight="bold")
    ax5.grid(axis="x", linestyle=":", alpha=0.5)

    figure.tight_layout(rect=[0, 0, 1, 0.978])
    figure.savefig(output, dpi=180)
    plt.close(figure)


def run_comparison(
    dataset: Dataset,
    output: Path,
    include_catboost: bool = True,
    extended_models: bool | None = None,
) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    is_cnc = dataset.name == "cnc_changeover"
    if extended_models is None:
        extended_models = True
    features = prepare_features(dataset)
    meta = dataset.metadata
    masks = {
        split: meta.split.eq(split) for split in ["train", "validation", "test"]
    }
    train, validation, test = (
        masks[name] for name in ["train", "validation", "test"]
    )
    if not all(mask.any() for mask in [train, validation, test]):
        raise ValueError("Train, validation, and test splits must all be nonempty")
    weights = group_weights(meta.loc[train, "group_id"])
    candidates: dict[str, Candidate] = {}
    results: dict[str, dict] = {}
    validation_predictions = []

    train_frame = features.loc[train]
    train_target = dataset.y.loc[train]
    val_frame = features.loc[validation]
    val_target = dataset.y.loc[validation]
    val_groups = meta.loc[validation, "group_id"]

    shared_encoder = encoder_for(train_frame)
    shared_matrix = shared_encoder.fit_transform(train_frame)
    encoded_cache = (shared_encoder, shared_matrix)

    def consider(candidate: Candidate, training_seconds: float):
        metrics, predicted = timed_validation(
            candidate,
            val_frame,
            val_target,
            val_groups,
        )
        current = results.get(candidate.name)
        if (
            current is None
            or metrics["group_macro_mae_min"]
            < current["metrics"]["group_macro_mae_min"]
        ):
            candidates[candidate.name] = candidate
            results[candidate.name] = {
                "parameters": candidate.parameters,
                "training_seconds": float(training_seconds),
                "metrics": metrics,
            }
            validation_predictions[:] = [
                row
                for row in validation_predictions
                if row["model"] != candidate.name
            ]
            validation_predictions.extend(
                {
                    "split": "validation",
                    "model": candidate.name,
                    "source_row": int(source_row),
                    "group_id": str(group),
                    "actual_min": float(actual),
                    "predicted_min": float(prediction),
                }
                for source_row, group, actual, prediction in zip(
                    meta.loc[validation, "source_row"],
                    val_groups,
                    val_target,
                    predicted,
                )
            )

    candidate, elapsed = fit_median(
        train_frame, train_target, meta.loc[train, "group_id"]
    )
    consider(candidate, elapsed)

    for alpha in [0.1, 1.0, 10.0, 100.0, 500.0] if is_cnc else [0.1, 1.0, 10.0, 100.0]:
        candidate, elapsed = fit_sklearn(
            "ridge",
            Ridge(alpha=alpha),
            {"alpha": alpha},
            train_frame,
            train_target,
            weights,
            encoded_cache=encoded_cache,
        )
        consider(candidate, elapsed)

    if extended_models:
        for alpha in [0.05, 0.2, 1.0]:
            for l1_ratio in [0.5, 0.8]:
                params = {"alpha": alpha, "l1_ratio": l1_ratio, "max_iter": 5000}
                candidate, elapsed = fit_sklearn(
                    "elastic_net",
                    ElasticNet(**params, random_state=SEED),
                    params,
                    train_frame,
                    train_target,
                    weights,
                    encoded_cache=encoded_cache,
                )
                consider(candidate, elapsed)

        for alpha in [0.1, 1.0, 10.0]:
            for epsilon in [1.2, 1.35]:
                huber_params = {"alpha": alpha, "epsilon": epsilon, "max_iter": 2000}
                candidate, elapsed = fit_sklearn(
                    "huber",
                    HuberRegressor(**huber_params),
                    huber_params,
                    train_frame,
                    train_target,
                    weights,
                    encoded_cache=encoded_cache,
                )
                consider(candidate, elapsed)

        max_k = max(1, len(train_frame) - 1)
        for n_neighbors in [k for k in [5, 15, 25] if k <= max_k]:
            for weight_mode in ["uniform", "distance"]:
                knn_params = {"n_neighbors": n_neighbors, "weights": weight_mode}
                candidate, elapsed = fit_sklearn(
                    "knn",
                    KNeighborsRegressor(**knn_params, n_jobs=1),
                    knn_params,
                    train_frame,
                    train_target,
                    weights,
                    encoded_cache=encoded_cache,
                )
                consider(candidate, elapsed)

        for depth in [6, 12, None]:
            for leaf in [3, 5, 15]:
                rf_params = {
                    "n_estimators": 150 if is_cnc else 250,
                    "max_depth": depth,
                    "min_samples_leaf": leaf,
                }
                candidate, elapsed = fit_sklearn(
                    "random_forest",
                    RandomForestRegressor(
                        **rf_params, random_state=SEED, n_jobs=1
                    ),
                    rf_params,
                    train_frame,
                    train_target,
                    weights,
                    encoded_cache=encoded_cache,
                )
                consider(candidate, elapsed)

    et_depths = [6, 12] if is_cnc else [None, 10, 20]
    et_leaves = [5, 20] if is_cnc else [1, 3, 5]
    et_trees = 150 if is_cnc else 300
    for depth in et_depths:
        for leaf in et_leaves:
            parameters = {
                "n_estimators": et_trees,
                "max_depth": depth,
                "min_samples_leaf": leaf,
            }
            model = ExtraTreesRegressor(
                **parameters,
                random_state=SEED,
                n_jobs=1,
            )
            candidate, elapsed = fit_sklearn(
                "extra_trees",
                model,
                parameters,
                train_frame,
                train_target,
                weights,
                encoded_cache=encoded_cache,
            )
            consider(candidate, elapsed)

    if extended_models:
        for loss_name in ["absolute_error", "squared_error", "huber"]:
            for depth in [3, 5]:
                for lr in [0.04, 0.08]:
                    gb_params = {
                        "loss": loss_name,
                        "n_estimators": 150,
                        "max_depth": depth,
                        "learning_rate": lr,
                        "min_samples_leaf": 5,
                    }
                    candidate, elapsed = fit_sklearn(
                        "gradient_boosting",
                        GradientBoostingRegressor(**gb_params, random_state=SEED),
                        gb_params,
                        train_frame,
                        train_target,
                        weights,
                        encoded_cache=encoded_cache,
                    )
                    consider(candidate, elapsed)

        for loss_name in ["absolute_error", "squared_error"]:
            for depth in [4, 6]:
                for lr in [0.03, 0.08]:
                    hgb_params = {
                        "loss": loss_name,
                        "max_iter": 200,
                        "max_depth": depth,
                        "learning_rate": lr,
                        "min_samples_leaf": 20 if is_cnc else 5,
                    }
                    candidate, elapsed = fit_sklearn(
                        "hist_gradient_boosting",
                        HistGradientBoostingRegressor(
                            **hgb_params, random_state=SEED
                        ),
                        hgb_params,
                        train_frame,
                        train_target,
                        weights,
                        encoded_cache=encoded_cache,
                    )
                    consider(candidate, elapsed)

        for hidden in [(64, 32), (128, 64)]:
            for alpha in [0.05, 0.5]:
                mlp_params = {
                    "hidden_layer_sizes": list(hidden),
                    "alpha": alpha,
                    "max_iter": 400,
                    "early_stopping": len(train_frame) >= 100,
                }
                candidate, elapsed = fit_sklearn(
                    "mlp",
                    MLPRegressor(
                        hidden_layer_sizes=hidden,
                        alpha=alpha,
                        max_iter=400,
                        early_stopping=len(train_frame) >= 100,
                        random_state=SEED,
                    ),
                    mlp_params,
                    train_frame,
                    train_target,
                    weights,
                    encoded_cache=encoded_cache,
                )
                consider(candidate, elapsed)

        for objective in ["mae", "rmse", "huber"]:
            for depth, leaves in [(4, 15), (6, 31)]:
                for lr in [0.03, 0.08]:
                    lgb_params = {
                        "objective": objective,
                        "n_estimators": 200,
                        "max_depth": depth,
                        "num_leaves": leaves,
                        "learning_rate": lr,
                        "min_child_samples": max(3, min(15, len(train_frame) // 8)),
                    }
                    candidate, elapsed = fit_lightgbm(
                        lgb_params,
                        train_frame,
                        train_target,
                        weights,
                        encoded_cache=encoded_cache,
                    )
                    consider(candidate, elapsed)

        for objective in ["reg:absoluteerror", "reg:squarederror", "reg:pseudohubererror"]:
            for depth in [4, 6]:
                for lr in [0.03, 0.08]:
                    xgb_params = {
                        "objective": objective,
                        "n_estimators": 200,
                        "max_depth": depth,
                        "learning_rate": lr,
                        "reg_lambda": 3.0,
                    }
                    candidate, elapsed = fit_xgboost(
                        xgb_params,
                        train_frame,
                        train_target,
                        weights,
                        encoded_cache=encoded_cache,
                    )
                    consider(candidate, elapsed)

    if include_catboost:
        cb_depths = [4, 6] if is_cnc else [4, 6, 8]
        cb_lrs = [0.03, 0.08] if is_cnc else [0.03, 0.1]
        cb_iters = 500 if is_cnc else 1000
        for loss_fn in ["MAE", "RMSE"]:
            for depth in cb_depths:
                for learning_rate in cb_lrs:
                    candidate, elapsed = fit_catboost(
                        {
                            "loss_function": loss_fn,
                            "depth": depth,
                            "learning_rate": learning_rate,
                            "iterations": cb_iters,
                        },
                        train_frame,
                        train_target,
                        weights,
                        val_frame,
                        val_target,
                    )
                    consider(candidate, elapsed)

    min_imp = 0.02 if is_cnc else 0.10
    winner, selection = choose_candidate(results, minimum_improvement=min_imp)
    final_candidate = candidates[winner]
    final_metrics, final_prediction = timed_validation(
        final_candidate,
        features.loc[test],
        dataset.y.loc[test],
        meta.loc[test, "group_id"],
    )
    # Compute test metrics and predictions for all trained candidate families
    all_test_metrics = {}
    test_predictions_by_model = {}
    all_test_prediction_rows = []
    for model_name in [m for m in MODEL_ORDER if m in candidates]:
        cand = candidates[model_name]
        m_test, pred_test = timed_validation(
            cand,
            features.loc[test],
            dataset.y.loc[test],
            meta.loc[test, "group_id"],
        )
        all_test_metrics[model_name] = m_test
        test_predictions_by_model[model_name] = pred_test
        all_test_prediction_rows.extend(
            {
                "split": "test",
                "model": model_name,
                "source_row": int(source_row),
                "group_id": str(group),
                "actual_min": float(actual),
                "predicted_min": float(prediction),
                "abs_error_min": float(abs(actual - prediction)),
            }
            for source_row, group, actual, prediction in zip(
                meta.loc[test, "source_row"],
                meta.loc[test, "group_id"],
                dataset.y.loc[test],
                pred_test,
            )
        )

    prediction_rows = validation_predictions + [
        {
            "split": "test",
            "model": winner,
            "source_row": int(source_row),
            "group_id": str(group),
            "actual_min": float(actual),
            "predicted_min": float(prediction),
        }
        for source_row, group, actual, prediction in zip(
            meta.loc[test, "source_row"],
            meta.loc[test, "group_id"],
            dataset.y.loc[test],
            final_prediction,
        )
    ]
    pd.DataFrame(prediction_rows).to_csv(output / "predictions.csv", index=False)
    all_rows = [
        {
            **row,
            "abs_error_min": float(abs(row["actual_min"] - row["predicted_min"])),
        }
        for row in validation_predictions
    ] + all_test_prediction_rows
    pd.DataFrame(all_rows).to_csv(output / "all_model_predictions.csv", index=False)

    comparison_plot(
        results,
        dataset.y.loc[test].to_numpy(),
        final_prediction,
        winner,
        output / "model_comparison.png",
        test_summary=all_test_metrics,
        test_predictions_by_model=test_predictions_by_model,
        dataset_name=dataset.name,
    )
    bundle = {
        "model_name": final_candidate.name,
        "parameters": final_candidate.parameters,
        "estimator": final_candidate.model,
        "encoder": final_candidate.encoder,
        "activity_medians": final_candidate.activity_medians,
        "transition_medians": final_candidate.transition_medians,
        "global_median": final_candidate.global_median,
        "categorical_columns": final_candidate.categorical_columns,
        "features": features.columns.tolist(),
        "target": dataset.target,
        "seed": SEED,
        "target_definition": dataset.notes["target_definition"],
        "candidates": candidates,
    }
    joblib.dump(bundle, output / "best_model.joblib", compress=3)
    input_sha256 = {}
    for path in dataset.paths:
        resolved = Path(path).resolve()
        label = (
            str(resolved.relative_to(ROOT))
            if resolved.is_relative_to(ROOT)
            else str(resolved)
        )
        input_sha256[label] = sha256(resolved)
    limitations = (
        [
            "30 changeover sessions from a single CNC machine; split by session chronologically.",
            "Target is online remaining changeover time (minutes) during setup, not pre-start static setup.",
            "Workshop schedule integration is an explicit rolling-horizon simulation assumption.",
        ]
        if is_cnc
        else [
            "S/D/B interval rows are mixed after Report Type removal.",
            "The target is observed report elapsed time, not verified processing time.",
            "No verified mapping exists to FJSP operations or machines.",
        ]
    )
    report = {
        "dataset": dataset.name,
        "representation": dataset.notes.get("representation", "default"),
        "target": dataset.target,
        "target_definition": dataset.notes["target_definition"],
        "features": features.columns.tolist(),
        "seed": SEED,
        "input_sha256": input_sha256,
        "split_rows": {name: int(mask.sum()) for name, mask in masks.items()},
        "split_groups": {
            name: int(meta.loc[mask, "group_id"].nunique())
            for name, mask in masks.items()
        },
        "validation": results,
        "selection": {**selection, "winner": winner},
        "final_holdout": {"model": winner, "metrics": final_metrics},
        "benchmark_test_summary": all_test_metrics,
        "limitations": limitations,
    }
    (output / "metrics.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return report


def run_cnc_representation_benchmark(
    output_dir: Path, include_catboost: bool = True
) -> dict:
    """Compare representations (selected, engineered, pca) and 7 ML algorithms on CNC changeover."""
    output_dir.mkdir(parents=True, exist_ok=True)
    rep_reports = {}
    for rep in ["selected", "engineered", "pca"]:
        ds = load_cnc_benchmark_dataset(representation=rep)
        rep_out = output_dir / rep
        rep_reports[rep] = run_comparison(
            ds, rep_out, include_catboost=include_catboost, extended_models=True
        )
    # Pick best representation by validation winner group_macro_mae_min
    best_rep = min(
        rep_reports,
        key=lambda r: rep_reports[r]["validation"][
            rep_reports[r]["selection"]["winner"]
        ]["metrics"]["group_macro_mae_min"],
    )
    best_report = rep_reports[best_rep]
    summary = {
        "dataset": "cnc_changeover",
        "target": "remaining_changeover_time_min",
        "best_representation_on_validation": best_rep,
        "winner_model": best_report["selection"]["winner"],
        "representations": {
            rep: {
                "feature_count": len(rep_reports[rep]["features"]),
                "validation_winner": rep_reports[rep]["selection"]["winner"],
                "validation_scores": {
                    m: rep_reports[rep]["validation"][m]["metrics"][
                        "group_macro_mae_min"
                    ]
                    for m in rep_reports[rep]["validation"]
                },
                "test_scores": {
                    m: rep_reports[rep]["benchmark_test_summary"][m][
                        "group_macro_mae_min"
                    ]
                    for m in rep_reports[rep]["benchmark_test_summary"]
                },
            }
            for rep in rep_reports
        },
    }
    (output_dir / "cnc_benchmark_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        choices=["production", "cnc", "cnc-all-reps"],
        default="production",
    )
    parser.add_argument(
        "--representation",
        choices=["selected", "engineered", "pca"],
        default="selected",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--skip-catboost", action="store_true", help=argparse.SUPPRESS
    )
    args = parser.parse_args()
    if args.dataset == "production":
        out = args.output or (ROOT / "reports" / "duration_model_comparison")
        report = run_comparison(
            load_production(), out, include_catboost=not args.skip_catboost
        )
        winner = report["selection"]["winner"]
        score = report["final_holdout"]["metrics"]["group_macro_mae_min"]
        print(f"Kazanan: {winner}; test grup-makro MAE: {score:.3f} dakika")
    elif args.dataset == "cnc":
        out = args.output or (
            ROOT / "reports" / "cnc_changeover_model_comparison" / args.representation
        )
        ds = load_cnc_benchmark_dataset(representation=args.representation)
        report = run_comparison(
            ds, out, include_catboost=not args.skip_catboost, extended_models=True
        )
        winner = report["selection"]["winner"]
        score = report["final_holdout"]["metrics"]["group_macro_mae_min"]
        print(
            f"CNC ({args.representation}) Kazanan: {winner}; "
            f"test grup-makro MAE: {score:.3f} dakika"
        )
    else:
        out = args.output or (ROOT / "reports" / "cnc_changeover_model_comparison")
        summary = run_cnc_representation_benchmark(
            out, include_catboost=not args.skip_catboost
        )
        best_rep = summary["best_representation_on_validation"]
        winner = summary["winner_model"]
        score = summary["representations"][best_rep]["test_scores"][winner]
        print(
            f"CNC Benchmark Tamamlandı -> En İyi Temsil: {best_rep}, "
            f"Kazanan Model: {winner}, Test Grup-Makro MAE: {score:.3f} dk"
        )


if __name__ == "__main__":
    from ml_experiments.compare_duration_models import main as run

    run()



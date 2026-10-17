"""Train-only duration feature selection, causal extraction, and held-out checks.

Run with: python -m ml_experiments.duration_features
The two existing target tables and raw sources are never overwritten.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import scipy
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.decomposition import PCA
from sklearn.feature_selection import SelectKBest, VarianceThreshold, mutual_info_regression
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Lasso, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/dataforNewVersion"
SEED = 42
PRODUCTION_FEATURES = ["Part Desc.", "Work Order  Qty", "Activity"]
CNC_METADATA = {
    "time", "changeover_session_id", "split", "history_seconds_available",
    "eligible_for_30s_window", "eligible_for_60s_window",
}
CNC_FORBIDDEN = {
    "source_row_index", "source_row_number", "derived_cycle_id", "derived_phase_run_id",
    "Line_Content", "Line_Content__was_missing", "Program_Stop", "Cycle_time_program",
    "Total_running_time_NC_program", "Net_running_time_program",
    "Tool_ID_Magazine_Place_49", "Magazine_9999_number_Place_1",
    "Magazine_9999_position_Place_1", "Tool_ID_Magazine_9999_Place_1",
}
SPLITS = ["train", "validation", "test"]


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_write(path, value):
    Path(path).write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def is_numeric(series):
    return pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series)


def categorical(series):
    return series.astype("string").fillna("__MISSING__").astype(str)


def cnc_feature_types(frame):
    """Controller/tool/slot identifiers are categories, not continuous measurements."""
    frame = frame.copy()
    exact = {"Operation_mode", "Program_status", "Magazine_status_1",
             "Magazine_9998_status", "Magazine_9999_status"}
    prefixes = ("Tool_number_", "Magazine_number_", "Magazine_position_",
                "Magazine_9998_number_", "Magazine_9998_position_",
                "Magazine_9999_number_", "Magazine_9999_position_")
    columns = [c for c in frame if c in exact or c.startswith(prefixes)]
    for column in columns:
        frame[column] = categorical(frame[column])
    return frame, columns


def balanced_indices(groups, limit=6000):
    """Bound diagnostic cost and stop long sessions from dominating MI/VIF."""
    groups = pd.Series(np.asarray(groups))
    budget = max(1, limit // groups.nunique())
    result = []
    for _, ids in groups.groupby(groups, sort=False).groups.items():
        ids = np.asarray(list(ids))
        result.extend(ids[np.linspace(0, len(ids) - 1, min(budget, len(ids))).astype(int)])
    return np.sort(np.asarray(result, dtype=int))


def vif_values(frame):
    """VIF on continuous standardized measurements, without dummy-variable traps."""
    x = StandardScaler().fit_transform(frame)
    result = {}
    for i, column in enumerate(frame):
        if x.shape[1] == 1:
            result[column] = 1.0
            continue
        others = np.delete(x, i, axis=1)
        residual = x[:, i] - others @ np.linalg.lstsq(others, x[:, i], rcond=None)[0]
        unexplained = float(np.mean(residual**2))
        result[column] = 1 / max(unexplained, 1e-12)
    return result


class DurationSelector:
    """Fit every selection decision on training rows; preserve original columns."""

    def __init__(self, k=24, variance_threshold=1e-4, dominance=.995,
                 correlation=.95, vif_threshold=20):
        self.k = k
        self.variance_threshold = variance_threshold
        self.dominance = dominance
        self.correlation = correlation
        self.vif_threshold = vif_threshold

    def fit(self, frame, target, groups):
        if len(frame) < 5 or not np.isfinite(np.asarray(target, dtype=float)).all():
            raise ValueError("Need at least five finite training targets")
        self.input_columns_ = frame.columns.tolist()
        self.numeric_ = [c for c in frame if is_numeric(frame[c])]
        self.categorical_ = [c for c in frame if c not in self.numeric_]
        self.medians_ = {}
        self.categories_ = {}
        encoded_values = {}
        discrete = {}
        dropped = {}
        variances = {}
        for c in frame:
            if c in self.numeric_:
                values = pd.to_numeric(frame[c], errors="coerce").astype(float)
                values = values.replace([np.inf, -np.inf], np.nan)
                median = values.median()
                self.medians_[c] = float(median) if pd.notna(median) else 0.0
                values = values.fillna(self.medians_[c])
                span = float(values.max() - values.min())
                # Range-normalization gives the threshold the same meaning across units.
                normalized = ((values - values.min()) / span) if span else values * 0
                selector = VarianceThreshold(threshold=self.variance_threshold)
                try:
                    selector.fit(normalized.to_numpy().reshape(-1, 1))
                    keep = bool(selector.get_support()[0])
                except ValueError:
                    keep = False
                variances[c] = float(normalized.var(ddof=0))
                discrete[c] = values.nunique() <= 20
                encoded_values[c] = values
                if not keep:
                    dropped[c] = "constant_or_near_constant_numeric"
            else:
                values = categorical(frame[c])
                self.categories_[c] = sorted(values.unique())
                encoded_values[c] = values.map({v: i for i, v in enumerate(self.categories_[c])})
                discrete[c] = True
                if values.value_counts(normalize=True).iloc[0] >= self.dominance:
                    dropped[c] = "constant_or_near_constant_category"

        encoded = pd.DataFrame(encoded_values, index=frame.index)
        retained = [c for c in frame if c not in dropped]
        # Deterministic preference: elapsed time, then the documented source order.
        if "elapsed_changeover_time_min" in retained:
            retained.insert(0, retained.pop(retained.index("elapsed_changeover_time_min")))
        numeric = [c for c in retained if c in self.numeric_]
        correlations = encoded[numeric].corr().abs()
        representatives = []
        correlated = []
        bijections = []
        for c in retained:
            matches = [a for a in representatives if a in numeric and c in numeric
                       and correlations.loc[a, c] >= self.correlation]
            if matches:
                representative = matches[0]
                dropped[c] = f"correlated_with:{representative}"
                correlated.append({"removed": c, "kept": representative,
                                   "absolute_pearson": float(correlations.loc[representative, c])})
                continue
            # Two nominal codes with a bijection carry identical training information.
            equivalent = None
            if c in self.categorical_:
                for a in representatives:
                    if a not in self.categorical_ or encoded[a].nunique() != encoded[c].nunique():
                        continue
                    if encoded.groupby(a)[c].nunique().max() == 1:
                        equivalent = a
                        break
            if equivalent is not None:
                dropped[c] = f"categorical_bijection_with:{equivalent}"
                bijections.append({"removed": c, "kept": equivalent})
            else:
                representatives.append(c)
        retained = representatives
        indices = balanced_indices(groups)
        sample = encoded.iloc[indices]
        # Numeric controller codes and binary flags do not have a continuous VIF meaning.
        continuous = [c for c in retained if c in self.numeric_ and not discrete[c]]
        vif_removed = []
        while continuous:
            vifs = vif_values(sample[continuous])
            worst = max(vifs, key=vifs.get)
            if vifs[worst] <= self.vif_threshold:
                break
            dropped[worst] = "continuous_vif_above_threshold"
            vif_removed.append({"removed": worst, "vif": vifs[worst]})
            continuous.remove(worst)
            retained.remove(worst)
        if not retained:
            raise ValueError("No usable features after variance/correlation/VIF filters")
        discrete_mask = [discrete[c] for c in retained]

        def score(x, y):
            return mutual_info_regression(x, y, discrete_features=discrete_mask,
                                          random_state=SEED, n_neighbors=3)

        kbest = SelectKBest(score_func=score, k=min(self.k, len(retained)))
        kbest.fit(sample[retained], np.asarray(target, dtype=float)[indices])
        self.selected_columns_ = [c for c, keep in zip(retained, kbest.get_support()) if keep]
        for c in retained:
            if c not in self.selected_columns_:
                dropped[c] = "below_mutual_information_top_k"
        self.report_ = {
            "fit_rows": len(frame), "fit_groups": int(pd.Series(groups).nunique()),
            "diagnostic_sample_rows": len(indices),
            "parameters": {"k": self.k, "range_normalized_variance_threshold": self.variance_threshold,
                           "categorical_dominance": self.dominance, "absolute_pearson": self.correlation,
                           "continuous_vif_threshold": self.vif_threshold, "seed": SEED},
            "input_features": self.input_columns_, "selected_features": self.selected_columns_,
            "dropped_features": dropped, "normalized_numeric_variances": variances,
            "correlation_removals": correlated, "vif_removals": vif_removed,
            "categorical_bijection_removals": bijections,
            "mutual_information": {c: float(v) for c, v in zip(retained, kbest.scores_)},
            "final_continuous_vif": vif_values(sample[continuous]) if continuous else {},
        }
        return self

    def transform(self, frame):
        return frame[self.selected_columns_].copy()


def encoder_for(frame):
    numeric = [c for c in frame if is_numeric(frame[c])]
    cat = [c for c in frame if c not in numeric]
    transformers = []
    if numeric:
        transformers.append(("numeric", make_pipeline(
            SimpleImputer(strategy="median", keep_empty_features=True), StandardScaler()), numeric))
    if cat:
        transformers.append(("category", OneHotEncoder(
            handle_unknown="ignore", sparse_output=False, dtype=np.float64), cat))
    return ColumnTransformer(transformers, verbose_feature_names_out=False)


def lasso_diagnostic(frame, y, groups):
    """L1 support is reported separately; it cannot veto nonlinear MI features."""
    idx = balanced_indices(groups)
    encoder = encoder_for(frame)
    matrix = encoder.fit_transform(frame.iloc[idx])
    target = np.log1p(np.asarray(y)[idx])
    alpha = max(float(np.std(target)) * .01, 1e-6)
    model = Lasso(alpha=alpha, max_iter=20000, tol=1e-5).fit(matrix, target)
    coefficients = {c: float(v) for c, v in zip(encoder.get_feature_names_out(), model.coef_)}
    return {"role": "diagnostic_only; MI retains possible nonlinear effects",
            "target_transform": "log1p(minutes)", "alpha": alpha,
            "iterations": int(model.n_iter_), "sample_rows": len(idx),
            "nonzero_encoded_features": sum(abs(v) > 1e-8 for v in coefficients.values()),
            "coefficients": coefficients}


def production_engineering(selected):
    """Extract known quantity scale without using post-completion outcomes."""
    result = selected.copy()
    if "Work Order  Qty" in result:
        quantity = pd.to_numeric(result.pop("Work Order  Qty"), errors="raise")
        if quantity.lt(0).any():
            raise ValueError("Negative work order quantity")
        result["log1p_work_order_qty"] = np.log1p(quantity)
    return result


def causal_windows(selected, metadata, windows=(30, 60)):
    """Only past/current rows, with full contiguous windows inside each session."""
    if selected.index.tolist() != metadata.index.tolist():
        raise ValueError("Features and window metadata must align")
    times = pd.to_datetime(metadata.time, errors="raise")
    groups = metadata.group_id
    if metadata.groupby("group_id").split.nunique().gt(1).any():
        raise ValueError("A session crosses splits")
    gaps = times.groupby(groups).diff().dt.total_seconds().dropna()
    if not gaps.eq(1).all():
        raise ValueError("Each session must have contiguous one-second timestamps")
    if not times.is_monotonic_increasing or times.duplicated().any():
        raise ValueError("Window timestamps must be ordered and unique")
    features = {c: selected[c].copy() for c in selected}
    for c in selected:
        # Elapsed time is exact at the prediction instant; rolling it adds no history.
        if c == "elapsed_changeover_time_min":
            continue
        if is_numeric(selected[c]):
            values = selected[c].astype(float)
            grouped = values.groupby(groups, sort=False)
            for window in windows:
                rolling = grouped.rolling(window, min_periods=window)
                for stat in ["mean", "std", "min", "max"]:
                    values_stat = getattr(rolling, stat)()
                    features[f"{c}__{stat}_{window}s"] = values_stat.droplevel(0).reindex(selected.index)
                features[f"{c}__delta_{window}s"] = values - grouped.shift(window - 1)
        else:
            values = categorical(selected[c])
            changes = values.ne(values.groupby(groups, sort=False).shift()).astype(float)
            changes.loc[groups.ne(groups.shift())] = 0
            for window in windows:
                counts = changes.groupby(groups, sort=False).rolling(window, min_periods=window).sum()
                features[f"{c}__changes_{window}s"] = counts.droplevel(0).reindex(selected.index)
    output = pd.DataFrame(features, index=selected.index)
    eligible = metadata.groupby("group_id", sort=False).cumcount().add(1).ge(max(windows))
    return output.loc[eligible].copy()


@dataclass
class Dataset:
    name: str
    target: str
    features: pd.DataFrame
    metadata: pd.DataFrame
    y: pd.Series
    paths: list[Path]
    notes: dict


def validate_splits(metadata, starts, ends):
    if not metadata.split.isin(SPLITS).all():
        raise ValueError("Unknown/missing split")
    if metadata.groupby("group_id").split.nunique().gt(1).any():
        raise ValueError("A group crosses splits")
    if pd.to_datetime(starts).isna().any() or pd.to_datetime(ends).isna().any():
        raise ValueError("Invalid interval")
    for left, right in zip(SPLITS, SPLITS[1:]):
        a, b = metadata.split.eq(left), metadata.split.eq(right)
        if not a.any() or not b.any():
            raise ValueError("Each split must be nonempty")
        if pd.to_datetime(ends[a]).max() > pd.to_datetime(starts[b]).min():
            raise ValueError("Training outcomes overlap the next prediction split")


def load_production(data_dir=DATA):
    from ml_experiments.prepare_data import build_production_target_dataset, split_production

    raw_path = data_dir / "production_analysis.csv"
    target_path = data_dir / "production_analysis_target_ready.csv"
    raw = pd.read_csv(raw_path)
    prepared, _ = build_production_target_dataset(raw)
    saved = pd.read_csv(target_path)
    pd.testing.assert_frame_equal(prepared.reset_index(drop=True), saved,
                                  check_dtype=False, rtol=1e-9, atol=1e-9)
    assignments = split_production(raw)
    meta = pd.DataFrame({"source_row": prepared.index,
                         "group_id": prepared["Case ID"],
                         "split": prepared["Case ID"].map(assignments["groups"])}, index=prepared.index)
    quarantine = meta.split.eq("boundary_quarantine")
    quarantined = int(quarantine.sum())
    meta = meta.loc[~quarantine].copy()
    validate_splits(meta, raw.loc[meta.index, "Start Timestamp"],
                    raw.loc[meta.index, "Complete Timestamp"])
    target = "target_elapsed_time"
    return Dataset("production_analysis", target, prepared.loc[meta.index, PRODUCTION_FEATURES],
                   meta, prepared.loc[meta.index, target], [raw_path, target_path], {
                       "target_definition": "mixed S/D/B observed report elapsed minutes; not verified machine runtime",
                       "excluded_rows_boundary_quarantine": quarantined,
                       "cutoffs": assignments["cutoffs"],
                       "excluded_columns": {
                           "Qty Completed": "outcome unavailable at prediction time",
                           "Qty Rejected": "outcome unavailable at prediction time",
                           "Qty for MRB": "outcome unavailable at prediction time",
                           "Worker ID": "identifier; not a known new-order input",
                           "Report Type": "removed after retaining all S/D/B interval rows",
                           "Resource": "machine assignment not confirmed before prediction",
                           "Case ID": "group metadata only",
                       },
                       "limitations": (
                           "S/D/B interval types are mixed after their type column is removed; "
                           "report-row aggregation and machine-runtime meaning remain unresolved"
                       ),
                   })


def load_cnc(data_dir=DATA):
    from ml_experiments.cnc_audit import audit
    from ml_experiments.prepare_data import build_cnc_remaining_time_dataset

    raw_path = data_dir / "cnc_changeover.csv"
    target_path = data_dir / "cnc_changeover_remaining_time_target.csv"
    raw = pd.read_csv(raw_path, low_memory=False)
    frame = pd.read_csv(target_path, low_memory=False)
    checked = audit(raw, frame)
    if not checked["numeric_checks_passed"]:
        raise ValueError(f"CNC input audit failed: {checked['errors']}")
    canonical_raw = raw.rename(columns={raw.columns[0]: "source_row_index"}) if str(
        raw.columns[0]).startswith("Unnamed:") else raw
    rebuilt, _ = build_cnc_remaining_time_dataset(canonical_raw)
    pd.testing.assert_frame_equal(rebuilt.reset_index(drop=True), frame,
                                  check_dtype=False, rtol=1e-9, atol=1e-9)
    target = "remaining_changeover_time_min"
    forbidden = CNC_METADATA | CNC_FORBIDDEN | {target}
    features = [c for c in frame if c not in forbidden and not c.startswith(("Label_", "review_", "Unnamed:"))]
    meta = pd.DataFrame({"source_row": pd.Index(raw.time).get_indexer(frame.time),
                         "group_id": frame.changeover_session_id,
                         "time": frame.time, "split": frame.split})
    validate_splits(meta, frame.time, frame.time)
    typed_features, nominal_columns = cnc_feature_types(frame[features])
    return Dataset("cnc_changeover", target, typed_features, meta, frame[target],
                   [raw_path, target_path], {
                       "target_definition": "remaining wall-clock minutes through final changeover sample",
                       "excluded_columns": sorted(set(frame.columns) - set(features) - {target}),
                       "input_audit_passed": True,
                       "numeric_controller_codes_treated_as_categories": nominal_columns,
                       "limitations": "30 sessions from one machine; live controller features only; source timezone unresolved",
                       "prediction_time": "during changeover, not before a new order starts",
                   })


def group_weights(groups):
    groups = pd.Series(np.asarray(groups))
    counts = groups.map(groups.value_counts()).to_numpy()
    return len(groups) / (groups.nunique() * counts)


def errors(actual, predictions, groups):
    actual = np.asarray(actual, dtype=float)
    predictions = np.asarray(predictions, dtype=float)
    if predictions.shape != actual.shape or not np.isfinite(predictions).all():
        raise ValueError("Invalid predictions")
    frame = pd.DataFrame({"group_id": np.asarray(groups),
                          "absolute_error_min": abs(actual - predictions)})
    group_errors = frame.groupby("group_id").absolute_error_min.mean()
    return {"rows": len(frame), "groups": len(group_errors),
            "row_mae_min": float(frame.absolute_error_min.mean()),
            "group_macro_mae_min": float(group_errors.mean()),
            "per_group_mae_min": {str(k): float(v) for k, v in group_errors.items()}}


def median_baseline(dataset, index):
    """Training-only operation median or session-balanced transition total median."""
    train = dataset.metadata.split.eq("train")
    if dataset.name == "production_analysis":
        history = pd.DataFrame({"activity": dataset.features.loc[train, "Activity"],
                                "target": dataset.y.loc[train]})
        medians = history.groupby("activity").target.median()
        return dataset.features.loc[index, "Activity"].map(medians).fillna(history.target.median()).to_numpy()
    # Exactly one total duration per training session; never use held-out session end.
    history = dataset.features.loc[train, ["transition_from_product", "transition_to_product",
                                          "elapsed_changeover_time_min"]].copy()
    history["total"] = dataset.y.loc[train] + history.elapsed_changeover_time_min
    history["group"] = dataset.metadata.loc[train, "group_id"]
    sessions = history.groupby("group").first()
    keys = ["transition_from_product", "transition_to_product"]
    medians = sessions.groupby(keys).total.median().to_dict()
    fallback = sessions.total.median()
    current = dataset.features.loc[index]
    total = [medians.get((r.transition_from_product, r.transition_to_product), fallback)
             for r in current.itertuples()]
    return np.maximum(0, np.asarray(total) - current.elapsed_changeover_time_min.to_numpy())


def export_frame(path, features, dataset):
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = dataset.metadata.loc[features.index]
    overlap = set(features) & (set(meta) | {dataset.target})
    if overlap:
        raise ValueError(f"Metadata/target included as features: {overlap}")
    output = pd.concat([meta, features, dataset.y.loc[features.index].rename(dataset.target)], axis=1)
    output.to_csv(path, index=False, float_format="%.9g")
    return {"path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
            "rows": len(output), "model_features": features.shape[1],
            "metadata_columns": meta.columns.tolist(), "target_column": dataset.target,
            "bytes": path.stat().st_size, "sha256": sha256(path)}


def artifact_path(dataset_name, kind, data_output):
    """Three training CSVs in biPre; other exploratory matrices stay in data too."""
    if dataset_name not in {"production_analysis", "cnc_changeover"} or kind not in {
        "selected", "engineered", "extracted"
    }:
        raise ValueError("Unknown dataset or artifact kind")
    primary = {("production_analysis", "engineered"), ("cnc_changeover", "selected"),
               ("cnc_changeover", "extracted")}
    data_output = Path(data_output).resolve()
    directory = (data_output if (dataset_name, kind) in primary else
                 data_output.parent / f"{data_output.name}_intermediate" / dataset_name)
    suffix = ".csv.gz" if kind == "engineered" and dataset_name == "cnc_changeover" else ".csv"
    return directory / f"{dataset_name}_{kind}{suffix}"


def relocate_existing_artifacts(report_output, data_output, dataset_names):
    """Move a previous experiment without fitting again or changing data bytes."""
    report_output, data_output = Path(report_output).resolve(), Path(data_output).resolve()
    migrated = []
    for dataset_name in dataset_names:
        report_directory = report_output / dataset_name
        report_path = report_directory / "report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        sources = []
        for kind, artifact in report["artifacts"].items():
            source = (ROOT / artifact["path"]).resolve()
            destination = artifact_path(dataset_name, kind, data_output)
            # Only touch the exact previous report artifact or its intended new destination.
            if source.parent != report_directory and source != destination:
                raise ValueError(f"Artifact is outside the intended report directory: {source}")
            if source.exists() and sha256(source) != artifact["sha256"]:
                raise ValueError(f"Source checksum mismatch: {source}")
            if destination.exists():
                if sha256(destination) != artifact["sha256"]:
                    raise FileExistsError(f"Different data already exists: {destination}")
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
                if sha256(destination) != artifact["sha256"]:
                    raise ValueError(f"Copied artifact checksum mismatch: {destination}")
            artifact["path"] = (str(destination.relative_to(ROOT))
                                if destination.is_relative_to(ROOT) else str(destination))
            if source != destination and source.exists():
                sources.append(source)
            migrated.append(destination)
        # Update references before removing the old copies; all matrices have verified copies.
        json_write(report_path, report)
        for source in sources:
            source.unlink()
    summary_path = report_output / "summary.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        # Preserve the hash of the original fitting script as experiment provenance.
        summary["artifact_layout"] = {
            "version": 2, "training_directory": str(data_output),
            "relocation_script_sha256": sha256(Path(__file__)),
        }
        json_write(summary_path, summary)
    return migrated


def transform_bundle(bundle, raw_features, metadata=None):
    """Apply saved training state to unseen rows (CNC needs up to 60s of history)."""
    selected = bundle["selector"].transform(raw_features)
    if bundle["target"] == "remaining_changeover_time_min":
        if metadata is None:
            raise ValueError("CNC transformation needs ordered session metadata and history")
        selected, _ = cnc_feature_types(selected)
        engineered = causal_windows(selected, metadata)
    else:
        engineered = production_engineering(selected)
    engineered = engineered[bundle["engineered_columns"]]
    encoded = bundle["extraction_encoder"].transform(engineered)
    components = bundle["pca"].transform(bundle["pca_scaler"].transform(encoded))
    return pd.DataFrame(components, index=engineered.index,
                        columns=[f"PC{i+1:03d}" for i in range(components.shape[1])])


def run_dataset(dataset, output, data_output=None):
    output.mkdir(parents=True, exist_ok=True)
    data_output = Path(data_output) if data_output is not None else output / "data/biPre"
    train = dataset.metadata.split.eq("train")
    selector = DurationSelector(k=24 if dataset.name == "cnc_changeover" else 3)
    selector.fit(dataset.features.loc[train], dataset.y.loc[train],
                 dataset.metadata.loc[train, "group_id"])
    selected = selector.transform(dataset.features)
    selection_report = selector.report_
    selection_report["lasso"] = lasso_diagnostic(
        selected.loc[train], dataset.y.loc[train], dataset.metadata.loc[train, "group_id"])
    pd.DataFrame([
        {"feature": c, "selected": c in selector.selected_columns_,
         "reason": selection_report["dropped_features"].get(c, "selected_mutual_information_top_k"),
         "mutual_information": selection_report["mutual_information"].get(c)}
        for c in dataset.features
    ]).to_csv(output / "feature_selection.csv", index=False)
    engineered = (causal_windows(selected, dataset.metadata) if dataset.name == "cnc_changeover"
                  else production_engineering(selected))
    common = engineered.index
    meta = dataset.metadata.loc[common]
    train_common = meta.split.eq("train")
    validation = meta.split.eq("validation")
    test = meta.split.eq("test")
    # Drop constants created by extraction on training only (e.g. stable category-change counts).
    keep_engineered = [c for c in engineered if engineered.loc[train_common, c].nunique() > 1]
    engineered_removed = sorted(set(engineered) - set(keep_engineered))
    engineered = engineered[keep_engineered]
    extraction_encoder = encoder_for(engineered.loc[train_common])
    training_encoded = extraction_encoder.fit_transform(engineered.loc[train_common])
    encoded = extraction_encoder.transform(engineered)
    # Standardize the encoded matrix too, so dummies and sensor aggregates share scale.
    pca_scaler = StandardScaler().fit(training_encoded)
    training_scaled = pca_scaler.transform(training_encoded)
    pca = PCA(n_components=.95, svd_solver="full", random_state=SEED).fit(training_scaled)
    components = pca.transform(pca_scaler.transform(encoded))
    extracted = pd.DataFrame(components, index=common,
                             columns=[f"PC{i+1:03d}" for i in range(components.shape[1])])
    representations = {"selected": selected.loc[common], "engineered": engineered, "pca": extracted}
    metrics = {}
    models = {}
    # Fixed probe, not a tuned duration model. Validation chooses the representation.
    for name, features in representations.items():
        encoder = encoder_for(features.loc[train_common])
        x_train = encoder.fit_transform(features.loc[train_common])
        weights = group_weights(meta.loc[train_common, "group_id"])
        model = Ridge(alpha=10).fit(x_train, dataset.y.loc[common[train_common]], sample_weight=weights)
        prediction = np.maximum(0, model.predict(encoder.transform(features.loc[validation])))
        metrics[name] = errors(dataset.y.loc[common[validation]], prediction,
                               meta.loc[validation, "group_id"])
        models[name] = (encoder, model)
    baseline_validation = median_baseline(dataset, common[validation])
    metrics["median_baseline"] = errors(dataset.y.loc[common[validation]], baseline_validation,
                                        meta.loc[validation, "group_id"])
    winner = min(metrics, key=lambda k: metrics[k]["group_macro_mae_min"])
    # The test target is evaluated only after the representation has been locked.
    if winner == "median_baseline":
        prediction = median_baseline(dataset, common[test])
    else:
        encoder, model = models[winner]
        prediction = np.maximum(0, model.predict(encoder.transform(representations[winner].loc[test])))
    heldout = errors(dataset.y.loc[common[test]], prediction, meta.loc[test, "group_id"])
    heldout["representation_chosen_on_validation"] = winner
    prediction_table = meta.loc[test].copy()
    prediction_table["actual_min"] = dataset.y.loc[common[test]]
    prediction_table["predicted_min"] = prediction
    prediction_table.to_csv(output / "holdout_predictions.csv", index=False, float_format="%.9g")
    artifacts = {}
    for name, features in [("selected", selected), ("engineered", engineered), ("extracted", extracted)]:
        artifacts[name] = export_frame(artifact_path(dataset.name, name, data_output), features, dataset)
    names = extraction_encoder.get_feature_names_out()
    pd.DataFrame(pca.components_, index=extracted.columns, columns=names).to_csv(
        output / "pca_loadings.csv", index_label="component", float_format="%.9g")
    # Reusable state: fit once on train, transform future inputs with the same vocabulary/basis.
    bundle = {"selector": selector, "extraction_encoder": extraction_encoder,
              "engineered_columns": keep_engineered, "pca_scaler": pca_scaler, "pca": pca,
              "probe_models": models, "validation_choice": winner,
              "training_baseline_inputs": {
                  "features": dataset.features.loc[train, ["Activity"] if dataset.name == "production_analysis"
                                                    else ["transition_from_product", "transition_to_product",
                                                          "elapsed_changeover_time_min"]],
                  "target": dataset.y.loc[train],
                  "groups": dataset.metadata.loc[train, "group_id"]},
              "seed": SEED, "target": dataset.target}
    # Class is importable even when invoked through python -m.
    joblib.dump(bundle, output / "transformers.joblib", compress=3)
    split_stats = {
        split: {"rows": int(meta.split.eq(split).sum()),
                "groups": int(meta.loc[meta.split.eq(split), "group_id"].nunique())}
        for split in SPLITS
    }
    report = {
        "dataset": dataset.name, "target": dataset.target, "target_unit": "minute",
        "notes": dataset.notes, "input_rows": len(dataset.features),
        "input_model_features": dataset.features.shape[1], "evaluation_splits": split_stats,
        "selection": selection_report,
        "extraction": {"windows_seconds": [30, 60] if dataset.name == "cnc_changeover" else [],
                       "causal": True, "future_rows_used": False,
                       "cold_start_rows_without_full_history": len(selected) - len(engineered),
                       "constant_engineered_columns_removed": engineered_removed,
                       "engineered_features": engineered.columns.tolist(),
                       "encoded_features_before_pca": len(names),
                       "pca_components": int(pca.n_components_),
                       "pca_explained_variance_ratio": pca.explained_variance_ratio_.tolist(),
                       "pca_retained_variance": float(pca.explained_variance_ratio_.sum()),
                       "categories_unknown_to_training": {
                           c: sorted(set(categorical(engineered[c])) -
                                     set(categorical(engineered.loc[train_common, c])))
                           for c in engineered if not is_numeric(engineered[c])}},
        "validation_metrics": metrics, "final_holdout": heldout,
        "probe": "fixed Ridge(alpha=10), equal weight per training group, predictions clipped at zero",
        "selection_rule": "minimum validation group-macro MAE, including the train-only median baseline",
        "warning": "Experimental feature comparison; PCA variance is not prediction accuracy. No operational model approval.",
        "artifacts": artifacts,
    }
    json_write(output / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=["all", "production", "cnc"], default="all")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/duration_features")
    parser.add_argument("--data-output", type=Path, default=DATA / "biPre")
    parser.add_argument("--relocate-existing", action="store_true",
                        help="Relocate recorded matrices and update references without refitting")
    args = parser.parse_args()
    loaders = [load_production, load_cnc] if args.dataset == "all" else [
        load_production if args.dataset == "production" else load_cnc]
    args.output = args.output.resolve()
    args.data_output = args.data_output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.relocate_existing:
        names = (["production_analysis", "cnc_changeover"] if args.dataset == "all" else
                 ["production_analysis" if args.dataset == "production" else "cnc_changeover"])
        moved = relocate_existing_artifacts(args.output, args.data_output, names)
        print(f"Verified and relocated {len(moved)} matrices; training CSVs: {args.data_output}")
        return
    reports = {}
    inputs = {}
    with threadpool_limits(limits=1):
        for loader in loaders:
            dataset = loader()
            inputs.update({str(p.relative_to(ROOT)): sha256(p) for p in dataset.paths})
            report = run_dataset(dataset, args.output / dataset.name, args.data_output)
            reports[dataset.name] = {
                "selected": len(report["selection"]["selected_features"]),
                "engineered": len(report["extraction"]["engineered_features"]),
                "pca": report["extraction"]["pca_components"],
                "holdout": report["final_holdout"],
            }
            print(f"{dataset.name}: {dataset.features.shape[1]} candidates -> "
                  f"{reports[dataset.name]['selected']} selected -> {reports[dataset.name]['pca']} PCs; "
                  f"validation choice: {report['final_holdout']['representation_chosen_on_validation']}", flush=True)
    for path, digest in inputs.items():
        if sha256(ROOT / path) != digest:
            raise ValueError(f"Input changed during experiment: {path}")
    json_write(args.output / "summary.json", {
        "input_sha256": inputs, "seed": SEED,
        "script_sha256": sha256(Path(__file__)),
        "artifact_layout": {"version": 2, "training_directory": str(args.data_output)},
        "versions": {"python": platform.python_version(), "numpy": np.__version__,
                     "pandas": pd.__version__, "scipy": scipy.__version__,
                     "sklearn": sklearn.__version__, "joblib": joblib.__version__},
        "fit_policy": "train only; group-disjoint chronological validation selection; final test once",
        "datasets": reports,
    })


if __name__ == "__main__":
    # Avoid pickling __main__.DurationSelector, which cannot be reloaded by another script.
    from ml_experiments.duration_features import main as run

    run()

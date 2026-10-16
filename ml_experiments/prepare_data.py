"""Profile, quality-check, split, and explore the two local datasets.

Raw files are read-only. Reports are written below reports/data_preparation/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 uses the project's pinned tomli dependency.
    import tomli as tomllib

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_PATH = ROOT / "configs" / "data_contracts.toml"
OUT = ROOT / "reports" / "data_preparation"
CONTRACTS = tomllib.loads(CONTRACTS_PATH.read_text(encoding="utf-8"))


def run_metadata() -> dict[str, Any]:
    return {"contract_version":CONTRACTS["version"],"inputs":{
        name:{"path":CONTRACTS[name]["path"],"source_url":CONTRACTS[name].get("source_url"),
              "source_version":CONTRACTS[name].get("source_version"),"sha256":sha256(ROOT/CONTRACTS[name]["path"])}
        for name in ["production_analysis","cnc_changeovers"]}}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(dataset: str) -> pd.DataFrame:
    path = ROOT / CONTRACTS[dataset]["path"]
    if dataset == "cnc_changeovers":
        frame = pd.read_csv(path, low_memory=False)
        # The leading empty header is a source row index, not an identifier.
        first = frame.columns[0]
        if str(first).startswith("Unnamed:"):
            frame = frame.rename(columns={first: "source_row_index"})
        return frame
    return pd.read_csv(path, low_memory=False)


def json_write(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def profile_one(dataset: str) -> dict[str, Any]:
    contract = CONTRACTS[dataset]
    path = ROOT / contract["path"]
    frame = read_csv(dataset)
    columns = []
    for col in frame.columns:
        series = frame[col]
        nonnull = series.dropna()
        numeric = pd.to_numeric(nonnull, errors="coerce")
        item: dict[str, Any] = {
            "name": str(col), "dtype": str(series.dtype), "missing_count": int(series.isna().sum()),
            "missing_fraction": float(series.isna().mean()), "distinct_non_null": int(nonnull.nunique()),
            "sample_values": [str(x) for x in nonnull.drop_duplicates().head(5).tolist()],
        }
        if len(nonnull) and numeric.notna().mean() >= 0.95:
            item["numeric_min"] = float(numeric.min())
            item["numeric_max"] = float(numeric.max())
        columns.append(item)
    time_range = None
    key = contract.get("time_key")
    if key in frame:
        ts = pd.to_datetime(frame[key], errors="coerce")
        time_range = {"valid": int(ts.notna().sum()), "invalid": int(ts.isna().sum()),
                      "min": str(ts.min()), "max": str(ts.max())}
    return {
        "dataset": dataset, "path": contract["path"], "source_url":contract.get("source_url"),
        "source_version":contract.get("source_version"),"source_license":contract.get("source_license"),
        "bytes": path.stat().st_size,
        "sha256": sha256(path), "rows": len(frame), "columns": len(frame.columns),
        "time_range": time_range, "sample_records": frame.head(3).astype(object).where(pd.notna(frame.head(3)), None).to_dict("records"),
        "column_profiles": columns,
    }


def profile() -> None:
    data = {name: profile_one(name) for name in ("production_analysis", "cnc_changeovers")}
    json_write(OUT / "raw_inventory.json", {"contract_version": CONTRACTS["version"], "datasets": data})
    print(f"Wrote {OUT / 'raw_inventory.json'}")


def issue(code: str, severity: str, mask: pd.Series, frame: pd.DataFrame, key: str, sample_cols: list[str]) -> dict[str, Any]:
    idx = frame.index[mask.fillna(False)]
    return {"issue_code": code, "severity": severity, "count": len(idx),
            "affected_source_rows": idx.tolist() if severity != "info" else [],
            "sample": frame.loc[idx, [c for c in sample_cols if c in frame]].head(8).to_dict("records")}


def production_quality(frame: pd.DataFrame) -> list[dict[str, Any]]:
    start = pd.to_datetime(frame["Start Timestamp"], errors="coerce")
    end = pd.to_datetime(frame["Complete Timestamp"], errors="coerce")
    elapsed = (end - start).dt.total_seconds() / 60
    span_text = frame["Span"].astype("string").str.strip()
    span_match = span_text.str.fullmatch(r"\d{1,}:\d{2}", na=False)
    span_min = pd.Series(np.nan, index=frame.index)
    parsed = span_text[span_match].str.extract(r"^(\d+):(\d{2})$").astype(float)
    span_min.loc[span_match] = parsed[0].to_numpy() * 60 + parsed[1].to_numpy()
    event_key = ["Case ID", "Activity", "Resource", "Start Timestamp", "Complete Timestamp", "Report Type"]
    dup_event = frame.duplicated(event_key, keep=False)
    case_nunique = frame.groupby("Case ID", dropna=False)[["Part Desc.", "Work Order  Qty"]].nunique(dropna=False)
    inconsistent_cases = case_nunique.gt(1).any(axis=1)
    inconsistent = frame["Case ID"].isin(inconsistent_cases[inconsistent_cases].index)
    qty_cols = ["Work Order  Qty", "Qty Completed", "Qty Rejected", "Qty for MRB"]
    qty = frame[qty_cols].apply(pd.to_numeric, errors="coerce")
    compare = pd.DataFrame({"Report Type":frame["Report Type"],"elapsed_min":elapsed,"span_min":span_min,"difference_min":span_min-elapsed})
    span_summary = compare.groupby("Report Type",dropna=False).agg(
        rows=("elapsed_min","size"), valid_span_rows=("span_min","count"),
        mismatch_over_one_minute=("difference_min",lambda x:int(x.abs().gt(1).sum())),
        span_shorter_than_elapsed=("difference_min",lambda x:int(x.lt(-1).sum())),
        span_longer_than_elapsed=("difference_min",lambda x:int(x.gt(1).sum())),
    ).reset_index().to_dict("records")
    event_duplicates = frame.duplicated(event_key,keep=False)
    return [
        issue("invalid_or_missing_timestamp", "error", start.isna() | end.isna(), frame, "Case ID", ["Case ID", "Start Timestamp", "Complete Timestamp"]),
        issue("negative_elapsed_minutes", "error", elapsed.lt(0), frame, "Case ID", ["Case ID", "Start Timestamp", "Complete Timestamp"]),
        issue("zero_elapsed_minutes", "review", elapsed.eq(0), frame, "Case ID", ["Case ID", "Activity", "Start Timestamp"]),
        issue("malformed_span", "review", ~span_match, frame, "Case ID", ["Case ID", "Span"]),
        issue("span_elapsed_mismatch_over_one_minute", "review", span_min.notna() & elapsed.notna() & (span_min - elapsed).abs().gt(1), frame, "Case ID", ["Case ID", "Span", "Start Timestamp", "Complete Timestamp"]),
        issue("exact_duplicate_row", "review", frame.duplicated(keep=False), frame, "Case ID", ["Case ID", "Activity", "Start Timestamp"]),
        issue("duplicate_event_key", "review", dup_event, frame, "Case ID", event_key),
        issue("case_part_or_order_qty_inconsistent", "review", inconsistent, frame, "Case ID", ["Case ID", "Part Desc.", "Work Order  Qty"]),
        issue("negative_quantity", "error", qty.lt(0).any(axis=1), frame, "Case ID", qty_cols),
        issue("reported_qty_exceeds_order_qty", "review", qty[["Qty Completed", "Qty Rejected", "Qty for MRB"]].sum(axis=1).gt(qty["Work Order  Qty"]), frame, "Case ID", qty_cols),
        issue("unknown_report_type", "review", ~frame["Report Type"].isin(["S", "D", "B"]), frame, "Case ID", ["Case ID", "Report Type"]),
        issue("rework_flag_missing", "info", frame["Rework"].isna(), frame, "Case ID", ["Case ID", "Activity", "Rework"]),
        {"issue_code":"span_elapsed_comparison_by_report_type", "severity":"info", "count":int((span_min-elapsed).abs().gt(1).sum()), "summary_by_report_type":span_summary, "sample":[]},
        {"issue_code":"duplicate_excess_row_counts", "severity":"info", "exact_duplicate_excess_rows":int(frame.duplicated(keep="first").sum()), "event_key_duplicate_excess_rows":int(frame.duplicated(event_key,keep="first").sum()), "affected_event_key_rows":int(event_duplicates.sum()), "sample":[]},
    ]


def cnc_sessions(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    labels = pd.to_numeric(frame["Label_03"], errors="coerce")
    run = labels.ne(labels.shift()).cumsum() - 1
    # Pair adjacent contiguous phases as one cycle; do not infer a label meaning.
    cycle = (run // 2).astype("int64")
    return run.astype("int64"), cycle


def cnc_quality(frame: pd.DataFrame) -> list[dict[str, Any]]:
    ts = pd.to_datetime(frame["time"], errors="coerce")
    delta = ts.diff().dt.total_seconds()
    labels = pd.to_numeric(frame["Label_03"], errors="coerce")
    allowed = set(labels.dropna().unique())
    session, cycle = cnc_sessions(frame)
    incomplete_cycle = session.ge(session.max()) if session.nunique() % 2 else pd.Series(False,index=frame.index)
    feature_cols = [c for c in frame if not str(c).startswith("Label_") and c not in {"time", "source_row_index"}]
    missing_cols = frame[feature_cols].isna().sum()
    numeric_cols = [c for c in feature_cols if pd.api.types.is_numeric_dtype(frame[c])]
    numeric = frame[numeric_cols]
    return [
        issue("invalid_timestamp", "error", ts.isna(), frame, "time", ["time"]),
        issue("non_increasing_timestamp", "error", delta.le(0), frame, "time", ["time"]),
        issue("sampling_gap_not_one_second", "review", delta.notna() & delta.ne(1), frame, "time", ["time"]),
        issue("missing_phase_marker", "error", labels.isna(), frame, "time", ["time", "Label_03"]),
        issue("phase_marker_not_integer", "error", labels.notna() & labels.mod(1).ne(0), frame, "time", ["time", "Label_03"]),
        {"issue_code":"source_index_repeats_across_sessions", "severity":"info", "count":int(frame["source_row_index"].duplicated(keep=False).sum()) if "source_row_index" in frame else 0,
         "sample":frame.loc[frame["source_row_index"].duplicated(keep=False), ["source_row_index","time"]].head(8).to_dict("records") if "source_row_index" in frame else []},
        {"issue_code":"derived_contiguous_phase_and_cycle_counts", "severity":"info", "count":int(cycle.nunique()), "phase_runs":int(session.nunique()), "observed_label_03":sorted(map(str,allowed)), "sample":[]},
        issue("unpaired_final_phase_run", "error", incomplete_cycle, frame, "time", ["time", "Label_03"]),
        {"issue_code":"sensor_columns_with_missing_values", "severity":"info", "count":int(missing_cols.gt(0).sum()), "columns":{str(k):int(v) for k,v in missing_cols[missing_cols.gt(0)].items()}, "sample":[]},
        {"issue_code":"constant_numeric_sensor_columns", "severity":"review", "count":int(numeric.nunique(dropna=False).le(1).sum()), "columns":numeric.nunique(dropna=False).loc[lambda s:s.le(1)].index.tolist(), "sample":[]},
    ]


def quality() -> None:
    reports = {}
    for name in ("production_analysis", "cnc_changeovers"):
        frame = read_csv(name)
        issues = production_quality(frame) if name == "production_analysis" else cnc_quality(frame)
        reports[name] = {"rows":len(frame), "issues":issues}
        statuses = [set() for _ in range(len(frame))]
        for item in issues:
            for row in item.get("affected_source_rows", []):
                statuses[int(row)].add(f"{item['severity']}:{item['issue_code']}")
        severity_codes = ["|".join(sorted(values)) for values in statuses]
        levels = ["quarantine" if any(code.startswith("error:") for code in values) else "review_required" if values else "valid" for values in statuses]
        if name == "production_analysis":
            identifiers = pd.DataFrame({"source_row":np.arange(len(frame)),"record_key":frame["Case ID"].astype(str)+"|"+frame["Activity"].astype(str)+"|"+frame["Start Timestamp"].astype(str)})
        else:
            identifiers = pd.DataFrame({"source_row":np.arange(len(frame)),"record_key":frame["time"].astype(str)+"|"+frame["source_row_index"].astype(str)})
        identifiers["quality_status"] = levels
        identifiers["issue_codes"] = severity_codes
        identifiers.to_csv(OUT / f"{name}_quality_manifest.csv",index=False)
    json_write(OUT / "quality_report.json", {"metadata":run_metadata(),"datasets":reports})
    print(f"Wrote {OUT / 'quality_report.json'}")


def split_production(frame: pd.DataFrame) -> dict[str, Any]:
    starts = pd.to_datetime(frame["Start Timestamp"], errors="coerce")
    ends = pd.to_datetime(frame["Complete Timestamp"], errors="coerce")
    work = pd.DataFrame({"group":frame["Case ID"], "start":starts, "end":ends}).groupby("group", dropna=False).agg(start=("start","min"),end=("end","max")).sort_values(["start","group"])
    ordered = work["start"].dropna().sort_values()
    cut1, cut2 = ordered.quantile([.60,.80]).tolist()
    status = {}
    boundary_details = []
    for case, row in work.iterrows():
        if pd.isna(row.start) or pd.isna(row.end):
            status[case] = "boundary_quarantine"
            boundary_details.append({"case_id":str(case),"start":str(row.start),"end":str(row.end),"span_days":None,"crossed_cutoffs":"missing_interval","source_rows":int(frame["Case ID"].eq(case).sum())})
        elif row.start < cut1 and row.end > cut1 or row.start < cut2 and row.end > cut2:
            status[case] = "boundary_quarantine"
            crossed=[]
            if row.start < cut1 and row.end > cut1: crossed.append("train_validation")
            if row.start < cut2 and row.end > cut2: crossed.append("validation_test")
            boundary_details.append({"case_id":str(case),"start":str(row.start),"end":str(row.end),"span_days":float((row.end-row.start).total_seconds()/86400),"crossed_cutoffs":"|".join(crossed),"source_rows":int(frame["Case ID"].eq(case).sum())})
        elif row.start <= cut1:
            status[case] = "train"
        elif row.start <= cut2:
            status[case] = "validation"
        else:
            status[case] = "test"
    return {"strategy":"chronological_case_group_60_20_20_with_cut_crossing_quarantine", "cutoffs":{"train_validation":str(pd.Timestamp(cut1)),"validation_test":str(pd.Timestamp(cut2))},
            "groups":{str(k):v for k,v in status.items()}, "group_counts":dict(Counter(status.values())),
            "boundary_reason_counts":dict(Counter(x["crossed_cutoffs"] for x in boundary_details)),"boundary_cases":boundary_details}


def split_cnc(frame: pd.DataFrame) -> dict[str, Any]:
    run, cycle = cnc_sessions(frame)
    ordered = pd.DataFrame({"cycle":cycle,"run":run}).drop_duplicates("run")
    cycle_ids = ordered["cycle"].drop_duplicates().tolist()
    n = len(cycle_ids)
    run_count = int(ordered["run"].nunique())
    if n != 30 or run_count != 60:
        raise ValueError(f"Expected 30 paired cycles / 60 contiguous phase runs from the recorded split design; found {n} cycles / {run_count} runs. Inspect phase pairing before splitting.")
    assignments = {str(c):("train" if i < 18 else "validation" if i < 24 else "test") for i,c in enumerate(cycle_ids)}
    return {"strategy":"ordered_cycle_holdout_18_6_6_cycles_grouped_into_3_1_1_matrices", "cycle_count":n,
            "matrix_count":math.ceil(n/6), "groups":assignments}


def splits() -> None:
    manifests = {}
    for name in ("production_analysis","cnc_changeovers"):
        frame = read_csv(name)
        result = split_production(frame) if name == "production_analysis" else split_cnc(frame)
        if name == "production_analysis":
            row_group = frame["Case ID"].astype(str)
        else:
            _, cycles = cnc_sessions(frame)
            row_group = cycles.astype(str)
        row_split = row_group.map(result["groups"]).fillna("boundary_quarantine")
        result["row_counts"] = {str(k):int(v) for k,v in row_split.value_counts().items()}
        result["split_overlap_count"] = int(pd.DataFrame({"group":row_group,"split":row_split}).groupby("group")["split"].nunique().gt(1).sum())
        result["group_key"] = CONTRACTS[name]["group_key"]
        result["time_key"] = CONTRACTS[name]["time_key"]
        if name == "production_analysis":
            start = pd.to_datetime(frame["Start Timestamp"],errors="coerce")
            end = pd.to_datetime(frame["Complete Timestamp"],errors="coerce")
            row_times = pd.DataFrame({"split":row_split,"start":start,"end":end})
            result["time_ranges"] = {str(k):{"start":str(g.start.min()),"end":str(g.end.max())} for k,g in row_times.groupby("split")}
            pd.DataFrame(result["boundary_cases"]).to_csv(OUT/"production_boundary_cases.csv",index=False)
            result.pop("boundary_cases")
        else:
            result["label_counts_by_split"] = {}
            for split_name in sorted(row_split.unique()):
                mask = row_split.eq(split_name)
                result["label_counts_by_split"][str(split_name)] = {
                    label:{str(k):int(v) for k,v in frame.loc[mask,label].value_counts(dropna=False).items()}
                    for label in ["Label_03","Label_10"]
                }
        manifests[name] = result
        # Row-level mapping makes downstream, train-only EDA reproducible without copying data.
        split_col = "Case ID" if name == "production_analysis" else "derived_cycle_id"
        rows = pd.DataFrame({"source_row":np.arange(len(frame)), "group_id":row_group, "split":row_split})
        rows.to_csv(OUT / f"{name}_split_manifest.csv", index=False)
    json_write(OUT / "split_summary.json", {"metadata":run_metadata(),"datasets":manifests})
    print(f"Wrote split manifests under {OUT}")


def eda() -> None:
    manifest = json.loads((OUT / "split_summary.json").read_text(encoding="utf-8"))["datasets"]
    OUT.mkdir(parents=True, exist_ok=True)
    summaries = {}
    # All target and feature summaries/plots below are computed on train rows only.
    p = read_csv("production_analysis")
    p_train_ids = {k for k,v in manifest["production_analysis"]["groups"].items() if v == "train"}
    p = p[p["Case ID"].astype(str).isin(p_train_ids)].copy()
    p["elapsed_min_observed"] = (pd.to_datetime(p["Complete Timestamp"],errors="coerce") - pd.to_datetime(p["Start Timestamp"],errors="coerce")).dt.total_seconds()/60
    p = p[p["elapsed_min_observed"].ge(0)]
    duration = p["elapsed_min_observed"].dropna()
    q1,q3 = duration.quantile([.25,.75]); iqr=q3-q1
    robust_z = .6745*(duration-duration.median())/max(float((duration-duration.median()).abs().median()),1e-12)
    order_qty = pd.to_numeric(p["Work Order  Qty"],errors="coerce")
    corr_frame = pd.DataFrame({"elapsed_min_observed":duration,"order_qty":order_qty.loc[duration.index]})
    cases = p.groupby("Case ID").agg(first_start=("Start Timestamp","min"),last_end=("Complete Timestamp","max"),report_rows=("Activity","size"))
    first_start=pd.to_datetime(cases.first_start,errors="coerce"); last_end=pd.to_datetime(cases.last_end,errors="coerce")
    cases["case_span_hours"]=(last_end-first_start).dt.total_seconds()/3600
    summaries["production_analysis"] = {"train_rows":len(p), "interpretation":"Observed timestamp elapsed time is descriptive only; not yet an approved processing-time target.",
        "elapsed_minutes":{"count":int(duration.count()),"median":float(duration.median()),"p90":float(duration.quantile(.9)),"p95":float(duration.quantile(.95)),"max":float(duration.max()) if len(duration) else None},
        "outlier_flags":{"iqr_fence_count":int(((duration < q1-1.5*iqr)|(duration > q3+1.5*iqr)).sum()),"robust_z_abs_gt_3_5_count":int(robust_z.abs().gt(3.5).sum()),"removed":0},
        "numeric_relationships":{"spearman_order_qty_vs_observed_elapsed":float(corr_frame.corr(method="spearman").iloc[0,1]) if corr_frame.dropna().shape[0]>2 else None},
        "case_descriptives":{"case_count":int(len(cases)),"median_report_rows":float(cases.report_rows.median()),"median_case_span_hours":float(cases.case_span_hours.median()),"max_case_span_hours":float(cases.case_span_hours.max())},
        "by_report_type":p.groupby("Report Type",dropna=False)["elapsed_min_observed"].agg(["count","median","mean","max"]).reset_index().to_dict("records"),
        "by_part_top15":p.groupby("Part Desc.")["elapsed_min_observed"].agg(["count","median"]).sort_values("count",ascending=False).head(15).reset_index().to_dict("records"),
        "leakage_fields":CONTRACTS["production_analysis"]["tabpfn"]["forbidden_features"], "unseen_category_risk":{c:sorted(set(p[c].dropna().astype(str)))[:100] for c in ["Activity","Resource","Part Desc."]}}
    fig, ax = plt.subplots(figsize=(8,4)); ax.hist(np.log1p(duration.clip(upper=duration.quantile(.99))),bins=35); ax.set(title="Production Analysis: train elapsed time (log1p, p99 clipped)",xlabel="log1p observed minutes",ylabel="records"); fig.tight_layout(); fig.savefig(OUT/"production_train_duration.png",dpi=130); plt.close(fig)
    c = read_csv("cnc_changeovers")
    _, cycle = cnc_sessions(c)
    c["derived_cycle_id"] = cycle.to_numpy()
    c_train_cycles = {int(k) for k,v in manifest["cnc_changeovers"]["groups"].items() if v == "train"}
    c = c[c["derived_cycle_id"].isin(c_train_cycles)].copy()
    label_counts = {str(k):int(v) for k,v in c["Label_03"].value_counts(dropna=False).items()}
    label10_counts = {str(k):int(v) for k,v in c["Label_10"].value_counts(dropna=False).items()}
    sensor_names = [col for col in c.columns if not str(col).startswith("Label_") and col not in ["time","source_row_index","derived_cycle_id"]]
    numeric_names = [col for col in sensor_names if pd.api.types.is_numeric_dtype(c[col])]
    numeric = c[numeric_names]
    var = numeric.var(numeric_only=True).sort_values()
    corr = numeric.loc[:,var[var.gt(0)].tail(40).index].corr().abs()
    upper = corr.where(np.triu(np.ones(corr.shape),k=1).astype(bool)).stack().sort_values(ascending=False).head(30)
    sessions = c.groupby("derived_cycle_id").agg(start=("time","min"),end=("time","max"),rows=("time","size"))
    phase_rows = c.groupby(["derived_cycle_id","Label_03"],dropna=False).size().rename("rows").reset_index()
    phase_duration = phase_rows.groupby("Label_03")["rows"].agg(["count","median","mean","max"]).reset_index().to_dict("records")
    summaries["cnc_changeovers"] = {"train_rows":len(c), "train_cycles":int(c["derived_cycle_id"].nunique()), "label_03_counts":label_counts,"label_10_counts":label10_counts,
        "sensor_missing_fraction_top20":c[sensor_names].isna().mean().sort_values(ascending=False).head(20).to_dict(), "constant_or_zero_variance_sensors":var[var.eq(0)].index.tolist(),
        "high_pairwise_correlations_top30":[{"feature_a":str(a),"feature_b":str(b),"abs_correlation":float(v)} for (a,b),v in upper.items()],
        "contiguous_phase_run_rows_by_label_03":phase_duration,
        "train_cycle_row_count":{"median":float(sessions.rows.median()),"min":int(sessions.rows.min()),"max":int(sessions.rows.max())},
        "note":"Rows are temporally dependent. Row counts overstate independent sample size; validation/test were not used in feature summaries or plots."}
    fig,ax=plt.subplots(figsize=(8,4)); pd.Series(label_counts,dtype=int).sort_index().plot.bar(ax=ax); ax.set(title="CNC Label_03 balance (train only)",xlabel="label",ylabel="one-second rows"); fig.tight_layout(); fig.savefig(OUT/"cnc_train_label03.png",dpi=130); plt.close(fig)
    json_write(OUT/"eda_train_summary.json",{"metadata":run_metadata(),"datasets":summaries})
    print(f"Wrote training-only EDA summary and plots under {OUT}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step",choices=["profile","quality","split","eda","all"])
    args = parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    steps={"profile":profile,"quality":quality,"split":splits,"eda":eda}
    if args.step == "all":
        for fn in steps.values(): fn()
    else:
        steps[args.step]()


if __name__ == "__main__":
    main()

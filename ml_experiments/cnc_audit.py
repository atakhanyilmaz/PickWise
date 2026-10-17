"""Read-only checks of CNC remaining-time data against raw sensor records."""

import argparse
import hashlib
import io
import json
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd


def audit(raw, target):
    """Check recorded label boundaries, not their unverified physical meaning."""
    report = {
        "errors": [],
        "warnings": [],
        "sessions": [],
        "numeric_checks_passed": False,
        "operational_use_approved": False,
    }

    def check(condition, message):
        if not condition:
            report["errors"].append(message)

    required = {
        "time",
        "changeover_session_id",
        "split",
        "transition_from_product",
        "transition_to_product",
        "elapsed_changeover_time_min",
        "remaining_changeover_time_min",
        "history_seconds_available",
        "eligible_for_30s_window",
        "eligible_for_60s_window",
    }
    check({"time", "Label_03"} <= set(raw), "Raw columns missing")
    check(
        required <= set(target),
        f"Target columns missing: {sorted(required - set(target))}",
    )
    if report["errors"]:
        return report
    raw, target = (
        raw.copy().reset_index(drop=True),
        target.copy().reset_index(drop=True),
    )
    rt = pd.to_datetime(raw.time, errors="coerce", format="mixed")
    tt = pd.to_datetime(target.time, errors="coerce", format="mixed")
    for name, times in (("raw", rt), ("target", tt)):
        check(not times.isna().any(), f"Invalid timestamps in {name}")
        check(times.is_unique, f"Duplicate timestamps in {name}")
        check(times.is_monotonic_increasing, f"Nonmonotonic timestamps in {name}")
    if report["errors"]:
        return report
    labels = pd.to_numeric(raw.Label_03, errors="coerce")
    check(labels.isin([0, 1]).all(), "Unexpected Label_03 values")
    if report["errors"]:
        return report
    phase_starts = labels.ne(labels.shift())
    raw_sessions = (phase_starts & labels.eq(0)).cumsum()
    expected = raw.loc[labels.eq(0)].copy()
    expected_ids = raw_sessions.loc[labels.eq(0)].to_numpy()
    check(
        target.time.tolist() == expected.time.tolist(),
        "Target coverage/order differs from raw Label_03=0 rows",
    )
    if report["errors"]:
        return report
    aligned = expected.reset_index(drop=True)
    sid = pd.to_numeric(target.changeover_session_id, errors="coerce")
    check(
        np.array_equal(sid.to_numpy(), expected_ids),
        "Session IDs disagree with contiguous raw phases",
    )
    check(
        target.split.isin(["train", "validation", "test"]).all(), "Unknown split values"
    )
    check(not target.isna().any().any(), "Missing values remain in target table")
    groups = target.groupby("changeover_session_id", sort=False)
    check(groups.split.nunique().eq(1).all(), "A session crosses splits")
    for c in [
        "elapsed_changeover_time_min",
        "remaining_changeover_time_min",
        "history_seconds_available",
    ]:
        values = pd.to_numeric(target[c], errors="coerce")
        check(
            np.isfinite(values).all() and values.ge(0).all(),
            f"Invalid/negative numeric values: {c}",
        )
    elapsed = pd.to_numeric(target.elapsed_changeover_time_min, errors="coerce")
    remaining = pd.to_numeric(target.remaining_changeover_time_min, errors="coerce")
    history = pd.to_numeric(target.history_seconds_available, errors="coerce")
    start = tt.groupby(target.changeover_session_id).transform("min")
    end = tt.groupby(target.changeover_session_id).transform("max")
    check(
        np.allclose(elapsed, (tt - start).dt.total_seconds() / 60),
        "Elapsed target differs from timestamps",
    )
    check(
        np.allclose(remaining, (end - tt).dt.total_seconds() / 60),
        "Remaining target differs from last sampled timestamp",
    )
    expected_history = groups.cumcount() + 1
    check(
        np.array_equal(history, expected_history),
        "history_seconds_available differs from observed row count",
    )
    for window in (30, 60):
        flag = target[f"eligible_for_{window}s_window"].astype(str).str.lower()
        check(flag.isin(["true", "false"]).all(), f"Invalid {window}s window flags")
        check(
            np.array_equal(flag.eq("true"), expected_history.ge(window)),
            f"Incorrect {window}s window eligibility",
        )

    report["missing_value_changes"] = []
    for c in aligned.columns.intersection(target.columns):
        if c == "time":
            continue
        missing = aligned[c].isna()
        left, right = aligned.loc[~missing, c], target.loc[~missing, c]
        ln, rn = (
            pd.to_numeric(left, errors="coerce"),
            pd.to_numeric(right, errors="coerce"),
        )
        equal = left.astype(str).eq(right.astype(str)) | (
            ln.notna() & rn.notna() & np.isclose(ln, rn)
        )
        check(equal.all(), f"Observed raw values changed: {c}")
        if missing.any():
            flag = f"{c}__was_missing"
            check(flag in target, f"Missing provenance flag: {c}")
            if flag in target:
                check(
                    np.array_equal(
                        pd.to_numeric(target[flag], errors="coerce"),
                        missing.astype(int),
                    ),
                    f"Incorrect missing provenance: {c}",
                )
            report["missing_value_changes"].append(
                {
                    "column": c,
                    "count": int(missing.sum()),
                    "fill_values": target.loc[missing, c]
                    .astype(str)
                    .value_counts()
                    .to_dict(),
                }
            )
    for session, frame in groups:
        idx = frame.index
        times = tt.loc[idx]
        first, last = times.iloc[0], times.iloc[-1]
        gaps = times.diff().dt.total_seconds().dropna().ne(1)
        following = rt[rt.gt(last)]
        next_index = following.index[0] if len(following) else None
        next_seconds = (
            float((following.iloc[0] - last).total_seconds())
            if len(following)
            else None
        )
        check(
            frame.transition_from_product.nunique() == 1
            and frame.transition_to_product.nunique() == 1,
            f"Transition changes inside session {session}",
        )
        check(
            not frame.transition_from_product.eq(frame.transition_to_product).any(),
            f"Self-transition in session {session}",
        )
        report["sessions"].append(
            {
                "session_id": str(session),
                "split": str(frame.split.iloc[0]),
                "from": str(frame.transition_from_product.iloc[0]),
                "to": str(frame.transition_to_product.iloc[0]),
                "rows": len(frame),
                "start": str(first),
                "last_changeover_sample": str(last),
                "sample_span_minutes": (last - first).total_seconds() / 60,
                "non_1s_steps": int(gaps.sum()),
                "next_sample_gap_seconds": next_seconds,
                "next_label03": float(labels.iloc[next_index])
                if next_index is not None
                else None,
            }
        )
    ranges = {}
    for split in ("train", "validation", "test"):
        times = tt[target.split.eq(split)]
        check(len(times) > 0, f"Empty split: {split}")
        if len(times):
            ranges[split] = {"start": str(times.min()), "end": str(times.max())}
    for a, b in (("train", "validation"), ("validation", "test")):
        if a in ranges and b in ranges:
            check(ranges[a]["end"] < ranges[b]["start"], f"Split time overlap: {a}/{b}")
    report.update(
        {
            "raw_rows": len(raw),
            "target_rows": len(target),
            "session_count": len(groups),
            "split_session_counts": groups.split.first().value_counts().to_dict(),
            "split_row_counts": target.split.value_counts().to_dict(),
            "split_time_ranges": ranges,
            "transition_session_counts": {
                f"{a}->{b}": int(n)
                for (a, b), n in groups[
                    ["transition_from_product", "transition_to_product"]
                ]
                .first()
                .value_counts()
                .items()
            },
            "removed_raw_columns": sorted(set(raw) - set(target)),
            "added_columns": sorted(set(target) - set(raw)),
            "raw_non_1s_steps": int(rt.diff().dt.total_seconds().dropna().ne(1).sum()),
            "within_changeover_non_1s_steps": sum(
                s["non_1s_steps"] for s in report["sessions"]
            ),
        }
    )
    report["warnings"] = [
        "The target is online remaining time, not pre-start total setup duration.",
        "Label_03=0 is the supplied phase convention; physical meaning and product mappings are not independently certified here.",
        "Zero target refers to the last changeover sample, not necessarily the next production boundary.",
        "Missing sentinels are encoding choices, not proof of physical absence of a tool or program line.",
        "Timestamp timezone is unspecified; no timezone was inferred.",
        "Rows within sessions are dependent; split and evaluate by session, never random sensor rows.",
        "Do not use remaining target, split, session ID, raw labels or absolute time as model features; review online availability of every sensor.",
        "No imputation-generation code or physical-boundary validation is established by this numeric audit.",
    ]
    if report["within_changeover_non_1s_steps"]:
        report["warnings"].append(
            "Sampling gaps exist inside changeover phases: row-count history is not elapsed seconds; window flags do not guarantee continuous 30/60 second histories."
        )
    report["numeric_checks_passed"] = not report["errors"]
    report["operational_use_approved"] = False
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default="origin/data_preprocesing")
    parser.add_argument("--output", type=Path, default=Path("results/cnc_audit.json"))
    args = parser.parse_args()
    commit = subprocess.check_output(
        ["git", "rev-parse", "--verify", f"{args.ref}^{{commit}}"], text=True
    ).strip()
    paths = {
        "raw": "data/dataforNewVersion/cnc_changeover.csv",
        "target": "data/dataforNewVersion/cnc_changeover_remaining_time_target.csv",
    }
    content = {
        k: subprocess.check_output(["git", "show", f"{commit}:{p}"])
        for k, p in paths.items()
    }
    frames = {
        k: pd.read_csv(io.BytesIO(v), low_memory=False) for k, v in content.items()
    }
    report = audit(frames["raw"], frames["target"])
    report["source_commit"] = commit
    report["sources"] = {
        k: {"path": paths[k], "sha256": hashlib.sha256(v).hexdigest()}
        for k, v in content.items()
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                k: v
                for k, v in report.items()
                if k not in ("sessions", "sources", "missing_value_changes")
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    raise SystemExit(1 if report["errors"] else 0)


if __name__ == "__main__":
    main()

"""Assess observable inter-resource gaps and whole-case spans, without training."""

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT = Path(__file__).resolve().parent


def named_machine(resource):
    """Name-based equipment subset; not independent physical verification."""
    return str(resource).startswith(("Machine", "Wire Cut - Machine"))


def distribution(values):
    values = pd.Series(values).dropna()
    if values.empty:
        return {"count": 0}
    return {
        "count": len(values),
        **{
            name: float(values.quantile(q))
            for name, q in (
                ("min", 0),
                ("p25", 0.25),
                ("median", 0.5),
                ("p75", 0.75),
                ("p95", 0.95),
                ("max", 1),
            )
        },
    }


def analyze(raw, manifest):
    required = {
        "Case ID",
        "Activity",
        "Resource",
        "Start Timestamp",
        "Complete Timestamp",
        "Part Desc.",
        "Work Order  Qty",
    }
    if not required <= set(raw):
        raise ValueError(f"Missing columns: {sorted(required - set(raw))}")
    work = raw.copy().reset_index(drop=True)
    work["source_row"] = work.index
    work["start"] = pd.to_datetime(work["Start Timestamp"], errors="coerce")
    work["end"] = pd.to_datetime(work["Complete Timestamp"], errors="coerce")
    if work[["start", "end"]].isna().any().any() or work.end.lt(work.start).any():
        raise ValueError("Invalid or reversed timestamps")
    mapping = manifest[["group_id", "split"]].drop_duplicates()
    if mapping.group_id.duplicated().any():
        raise ValueError("One case appears in multiple splits")
    splits = mapping.set_index("group_id").split.to_dict()
    if not set(work["Case ID"]) <= set(splits):
        raise ValueError("Missing case split mapping")
    original = list(raw.columns)
    duplicate_mask = work.duplicated(original, keep=False)
    events = [
        "Case ID",
        "Activity",
        "Resource",
        "Start Timestamp",
        "Complete Timestamp",
    ]
    event_mask = work.duplicated(events, keep=False)
    work["exact_duplicate"] = duplicate_mask
    work["event_duplicate"] = event_mask
    cases, pairs = [], []
    for case_id, frame in work.groupby("Case ID", sort=False):
        frame = frame.sort_values(["start", "end", "source_row"], kind="stable")
        prior_max_end = frame.end.cummax().shift()
        overlap = frame.start.lt(prior_max_end)
        tied = frame.start.duplicated(keep=False)
        duration = (frame.end - frame.start).dt.total_seconds() / 60
        span = (frame.end.max() - frame.start.min()).total_seconds() / 60
        cases.append(
            {
                "case_id": str(case_id),
                "split": splits[case_id],
                "rows": len(frame),
                "resources": int(frame.Resource.nunique()),
                "activities": int(frame.Activity.nunique()),
                "part_count": int(frame["Part Desc."].nunique(dropna=False)),
                "quantity_count": int(frame["Work Order  Qty"].nunique(dropna=False)),
                "observed_case_span_minutes": span,
                "sum_report_interval_minutes": float(duration.sum()),
                "overlapping_rows": int(overlap.sum()),
                "tied_start_rows": int(tied.sum()),
                "exact_duplicate_rows": int(frame.exact_duplicate.sum()),
                "event_duplicate_rows": int(frame.event_duplicate.sum()),
                "start": str(frame.start.min()),
                "end": str(frame.end.max()),
            }
        )
        rows = list(frame.to_dict("records"))
        for left, right in zip(rows, rows[1:]):
            if left["Resource"] == right["Resource"]:
                continue
            gap = (right["start"] - left["end"]).total_seconds() / 60
            # Necessary timestamp checks, not proof these reports are a true handoff.
            ambiguous = (
                left["event_duplicate"]
                or right["event_duplicate"]
                or tied.loc[left["source_row"]]
                or tied.loc[right["source_row"]]
                or overlap.loc[right["source_row"]]
            )
            pairs.append(
                {
                    "case_id": str(case_id),
                    "split": splits[case_id],
                    "source_row_a": int(left["source_row"]),
                    "source_row_b": int(right["source_row"]),
                    "resource_a": str(left["Resource"]),
                    "resource_b": str(right["Resource"]),
                    "activity_a": str(left["Activity"]),
                    "activity_b": str(right["Activity"]),
                    "observed_adjacent_gap_minutes": gap,
                    "nonnegative_unambiguous_timestamps": bool(
                        gap >= 0 and not ambiguous
                    ),
                    "both_named_machining_resources": all(
                        named_machine(r["Resource"]) for r in (left, right)
                    ),
                }
            )
    cf = pd.DataFrame(cases)
    pf = pd.DataFrame(pairs)
    report = {
        "raw_rows": len(raw),
        "case_count": len(cf),
        "resource_count": int(work.Resource.nunique()),
        "resource_names": sorted(work.Resource.dropna().unique().tolist()),
        "exact_duplicate_excess_rows": int(raw.duplicated().sum()),
        "event_key_duplicate_excess_rows": int(raw.duplicated(events).sum()),
        "cases_with_overlapping_intervals": int(cf.overlapping_rows.gt(0).sum()),
        "cases_with_tied_starts": int(cf.tied_start_rows.gt(0).sum()),
        "cases_with_event_duplicates": int(cf.event_duplicate_rows.gt(0).sum()),
        "cases_with_multiple_parts_or_quantities": int(
            (cf.part_count.ne(1) | cf.quantity_count.ne(1)).sum()
        ),
        "cases_with_report_sum_greater_than_case_span": int(
            cf.sum_report_interval_minutes.gt(cf.observed_case_span_minutes).sum()
        ),
        "observed_case_span_minutes": distribution(cf.observed_case_span_minutes),
        "case_counts_by_split": cf.split.value_counts().to_dict(),
        "case_span_by_split": {
            s: distribution(g.observed_case_span_minutes)
            for s, g in cf.groupby("split")
        },
        "case_overlap_by_split": {
            s: int(g.overlapping_rows.gt(0).sum()) for s, g in cf.groupby("split")
        },
        "cases_with_single_resource": int(cf.resources.eq(1).sum()),
        "observed_case_span_is_verified_order_lead_time": False,
        "adjacent_gap_is_verified_machine_transfer_time": False,
    }
    if len(pf):
        usable = pf[pf.nonnegative_unambiguous_timestamps]
        count_by_edge = (
            usable.groupby(["resource_a", "resource_b", "split"])
            .size()
            .unstack(fill_value=0)
        )
        edge_cases = (
            usable.groupby(["resource_a", "resource_b", "split"])
            .case_id.nunique()
            .unstack(fill_value=0)
        )
        for split in ("train", "validation", "test"):
            if split not in edge_cases:
                edge_cases[split] = 0
        coverage = edge_cases[
            (edge_cases[["train", "validation", "test"]] > 0).all(axis=1)
        ]
        report.update(
            {
                "adjacent_different_resource_pairs": len(pf),
                "negative_gap_pairs": int(pf.observed_adjacent_gap_minutes.lt(0).sum()),
                "zero_gap_pairs": int(pf.observed_adjacent_gap_minutes.eq(0).sum()),
                "positive_gap_pairs": int(pf.observed_adjacent_gap_minutes.gt(0).sum()),
                "timestamp_screened_pairs": len(usable),
                "timestamp_screened_pair_cases": int(usable.case_id.nunique()),
                "timestamp_screened_pair_counts_by_split": usable.split.value_counts().to_dict(),
                "timestamp_screened_case_counts_by_split": usable.groupby("split")
                .case_id.nunique()
                .to_dict(),
                "timestamp_screened_gap_minutes": distribution(
                    usable.observed_adjacent_gap_minutes
                ),
                "screened_pairs_over_one_day": int(
                    usable.observed_adjacent_gap_minutes.gt(1440).sum()
                ),
                "screened_named_machine_to_machine_pairs": int(
                    usable.both_named_machining_resources.sum()
                ),
                "screened_named_machine_pair_cases": int(
                    usable[usable.both_named_machining_resources].case_id.nunique()
                ),
                "edges_seen_in_all_three_splits": len(coverage),
                "edge_case_coverage": [
                    {"from": a, "to": b, **{s: int(n) for s, n in row.items()}}
                    for (a, b), row in edge_cases.iterrows()
                ],
                "edge_row_counts": [
                    {"from": a, "to": b, **{s: int(n) for s, n in row.items()}}
                    for (a, b), row in count_by_edge.iterrows()
                ],
            }
        )
    report["limitations"] = [
        "Sorted adjacent reports are not verified operation predecessors or material transfers.",
        "Overlap can reflect batches, partial reports, parallel work or data errors; do not silently delete it.",
        "Case span excludes any unrecorded time before the first or after the last event; shipment/acceptance endpoints are not certified.",
        "Report Type S/D/B and source timezone remain unresolved.",
        "Part and quantity consistency does not prove all records describe one indivisible part.",
        "Only descriptive integrity statistics are produced; no model fit, feature selection or success claim.",
    ]
    # Sensitivity check: skipping quality/other stations changes the question.
    # These are chronological machining pairs, NOT verified direct transfers.
    skip_pairs = []
    machining = work[work.Resource.map(named_machine)]
    for case_id, frame in machining.groupby("Case ID", sort=False):
        rows = list(
            frame.sort_values(["start", "end", "source_row"]).to_dict("records")
        )
        for left, right in zip(rows, rows[1:]):
            if left["Resource"] != right["Resource"]:
                skip_pairs.append(
                    {
                        "case": case_id,
                        "split": splits[case_id],
                        "gap": (right["start"] - left["end"]).total_seconds() / 60,
                    }
                )
    sf = pd.DataFrame(skip_pairs)
    if len(sf):
        positive = sf[sf.gap.ge(0)]
        report["sensitivity_skipping_intermediate_stations"] = {
            "chronological_machine_pairs": len(sf),
            "nonnegative_pairs": len(positive),
            "cases_with_any_pair": int(sf.case.nunique()),
            "nonnegative_pairs_by_split": positive.split.value_counts().to_dict(),
            "verified_direct_transfers": False,
        }
    return report, cf, pf


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--raw",
        type=Path,
        default=ROOT / "data/dataforNewVersion/production_analysis.csv",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT
        / "reports/data_preparation/production_analysis_split_manifest.csv",
    )
    parser.add_argument(
        "--output", type=Path, default=EXPERIMENT / "results" / "process_target_audit"
    )
    args = parser.parse_args()
    report, cases, pairs = analyze(pd.read_csv(args.raw), pd.read_csv(args.manifest))
    report["sources"] = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (args.raw, args.manifest)
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    cases.to_csv(args.output / "cases.csv", index=False)
    pairs.to_csv(args.output / "adjacent_resource_pairs.csv", index=False)
    print(
        json.dumps(
            {
                k: v
                for k, v in report.items()
                if k
                not in (
                    "edge_case_coverage",
                    "edge_row_counts",
                    "resource_names",
                    "sources",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

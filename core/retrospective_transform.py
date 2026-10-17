"""Production Analysis records → a solvable workshop scenario and order drafts.

Source: Production Analysis with Process Mining Technology (figshare 12697997), 2012 records
in data/dataforNewVersion/production_analysis.csv. The transform is deliberately conservative:

- Only machine resources ("Machine N", "Wire Cut - Machine 13") become machines; quality
  checks, packing, oven and manual work are left out of the plan.
- One operation = consecutive records of the same activity in a work order; repeated and
  overlapping reports are merged, never added up twice.
- Each operation may run only on the machine it was recorded on (no inferred alternatives).
- Duration = median observed elapsed minutes of that activity on that machine over every work
  order (DurationSource.HISTORICAL_MEDIAN). Elapsed time is not verified net machine time and
  ignores order quantity (ADR 0002).
- Routes inferred from records are labelled DEMO_ASSUMPTION, not user approval
  (docs/plan-data-contract.md); an edited and approved draft becomes USER_APPROVED in the UI.

Seeding (writes no Git commit):

    python -m core.retrospective_transform --record /tmp/v1.json
    python -m benchmarks.plan_storage_cli --db database/local/workshop.sqlite3 save \
        --record /tmp/v1.json --first-version --confirm-save
"""

import argparse
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from core.domain_rules import (
    DurationSource,
    JobModel,
    MachineModel,
    OperationModel,
    RouteSource,
    WorkshopScenario,
)
from core.plan_contract import StoredPlanVersion
from core.scenarios import create_snapshot
from core.validation import validate_workshop

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/dataforNewVersion/production_analysis.csv"
SCENARIO_ID = "production-analysis-2012"
PLAN_ID = "synthetic-workshop"  # the id ui/pages.py reads
WINDOW_START = (
    "2012-03-05"  # first jobs whose first machine record starts on or after this
)
PLAN_JOBS = 10
DRAFT_JOBS = 3
MACHINE = re.compile(r"Machine\s*(\d+)")


def load_records(path=SOURCE):
    """Machine rows with parsed timestamps and positive elapsed time, in record order."""
    frame = pd.read_csv(path)
    frame.columns = [" ".join(column.split()) for column in frame.columns]
    frame["start"] = pd.to_datetime(
        frame["Start Timestamp"], format="%Y/%m/%d %H:%M:%S.%f"
    )
    frame["end"] = pd.to_datetime(
        frame["Complete Timestamp"], format="%Y/%m/%d %H:%M:%S.%f"
    )
    frame["machine_id"] = frame["Resource"].str.extract(MACHINE, expand=False)
    machines = frame["machine_id"].notna() & ~frame["Resource"].str.startswith("Manual")
    frame = frame[machines & (frame["end"] > frame["start"])].copy()
    frame["machine_id"] = frame["machine_id"].astype(int)
    frame["case"] = frame["Case ID"].str.extract(r"(\d+)", expand=False).astype(int)
    return frame.sort_values(["case", "start", "end"], kind="stable")


def busy_minutes(rows):
    """Minutes covered by the union of [start, end) intervals: overlaps count once."""
    total, current_start, current_end = 0.0, None, None
    for start, end in sorted(zip(rows["start"], rows["end"])):
        if current_end is None or start > current_end:
            if current_end is not None:
                total += (current_end - current_start).total_seconds()
            current_start, current_end = start, end
        else:
            current_end = max(current_end, end)
    total += (current_end - current_start).total_seconds()
    return total / 60


def recorded_operations(records):
    """Per work order: consecutive same-activity rows merged into one operation."""
    records = records.copy()
    step = (records["Activity"] != records.groupby("case")["Activity"].shift()).cumsum()
    operations = (
        records.groupby([records["case"], step], sort=False)
        .apply(
            lambda rows: pd.Series(
                {
                    "activity": rows["Activity"].iloc[0],
                    "machine_id": rows["machine_id"].iloc[0],
                    "resource": rows["Resource"].iloc[0],
                    "part": rows["Part Desc."].iloc[0],
                    "start": rows["start"].min(),
                    "minutes": busy_minutes(rows),
                }
            ),
            include_groups=False,
        )
        .reset_index(level=1, drop=True)
        .reset_index()
    )
    return operations


def machine_name(resource, machine_id):
    """'Machine 4 - Turning & Milling' → 'M4 Turning & Milling' (Gemma matches 'M4' to id 4)."""
    kind = MACHINE.sub("", resource).replace("-", " ").strip()
    return f"M{machine_id} {' '.join(kind.split())}"


def build_jobs(operations, cases, medians, route_source):
    jobs = []
    for case in cases:
        rows = operations[operations["case"] == case]
        jobs.append(
            JobModel(
                job_id=case,
                name=f"İş emri {case} · {rows['part'].iloc[0]}",
                route_source=route_source,
                operations=[
                    OperationModel(
                        operation_id=index,
                        name=MACHINE.sub("", row.activity).strip(" -"),
                        processing_times={
                            row.machine_id: medians[(row.activity, row.machine_id)]
                        },
                        duration_source=DurationSource.HISTORICAL_MEDIAN,
                    )
                    for index, row in enumerate(rows.itertuples(), start=1)
                ],
            )
        )
    return jobs


def production_inputs(records=None):
    """(operations, medians, ordered cases) shared by the scenario and the drafts."""
    records = load_records() if records is None else records
    operations = recorded_operations(records)
    medians = (
        operations.groupby(["activity", "machine_id"])["minutes"]
        .median()
        .round()
        .clip(lower=1)
        .astype(int)
        .to_dict()
    )
    first = operations.groupby("case")["start"].min().sort_values(kind="stable")
    ordered = list(first[first >= pd.Timestamp(WINDOW_START)].index)
    return operations, medians, ordered


def build_scenario(records=None, jobs=PLAN_JOBS):
    operations, medians, ordered = production_inputs(records)
    cases = ordered[:jobs]
    used = operations[operations["case"].isin(cases)]
    names = dict(zip(used["machine_id"], used["resource"]))
    return WorkshopScenario(
        scenario_id=SCENARIO_ID,
        description=(
            f"Production Analysis 2012 kayıtlarından {len(cases)} iş emri "
            f"({WINDOW_START} sonrası ilk başlayanlar); yalnız tezgâh işlemleri."
        ),
        machines=[
            MachineModel(machine_id=machine_id, name=machine_name(resource, machine_id))
            for machine_id, resource in sorted(names.items())
        ],
        jobs=build_jobs(operations, cases, medians, RouteSource.DEMO_ASSUMPTION),
        time_unit_note=(
            "Süreler, aynı faaliyetin aynı tezgâhta bütün iş emirlerinde gözlenen geçen "
            "sürelerinin medyanıdır (dakika). Saf makine süresi değildir; sipariş adedi "
            "dikkate alınmaz. Rotalar kayıttan çıkarıldığı için demo varsayımıdır. "
            "Kesintisiz çalışma varsayılır."
        ),
    )


def order_drafts(scenario, records=None, count=DRAFT_JOBS):
    """Next recorded work orders that use only the plan's machines, as new-order drafts."""
    operations, medians, ordered = production_inputs(records)
    planned = {job.job_id for job in scenario.jobs}
    machines = {machine.machine_id for machine in scenario.machines}
    cases = [
        case
        for case in ordered
        if case not in planned
        and set(operations.loc[operations["case"] == case, "machine_id"]) <= machines
    ][:count]
    return build_jobs(operations, cases, medians, RouteSource.DEMO_ASSUMPTION)


def initial_record(approved_by, version_id="v1", time_limit=10):
    """First plan version, solved and independently validated before it can be stored."""
    snapshot = create_snapshot(build_scenario(), version_id, time_limit=time_limit)
    rows = [row.model_dump() for row in snapshot.result.schedule]
    violations = validate_workshop(snapshot.scenario, rows)
    if violations:
        raise ValueError(f"Initial plan failed validation: {violations}")
    return StoredPlanVersion(
        plan_id=PLAN_ID,
        parent_version_id=None,
        approved_by=approved_by,
        approved_at=datetime.now(ZoneInfo("Europe/Istanbul")),
        snapshot=snapshot,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--approved-by", required=True)
    args = parser.parse_args()
    record = initial_record(args.approved_by)
    args.record.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    result = record.snapshot.result
    print(
        f"{record.snapshot.version_id}: {len(record.snapshot.scenario.jobs)} iş, "
        f"{len(record.snapshot.scenario.machines)} tezgâh, {result.status}, "
        f"makespan {result.makespan} dk → {args.record}"
    )


if __name__ == "__main__":
    main()

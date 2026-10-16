"""Run: python -m benchmarks.brandimarte_runner --time-limit 10"""

import argparse
import csv
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import ortools
import plotly.graph_objects as go

from core.cpsat_solver import UPSTREAM, baseline, check_upstream, read_instance, solve
from core.validation import validate


def gantt(rows, title, target):
    fig = go.Figure()
    for j in sorted({r["job"] for r in rows}):
        group = [r for r in rows if r["job"] == j]
        fig.add_trace(
            go.Bar(
                name=f"İş {j + 1}",
                orientation="h",
                y=[f"M{r['machine'] + 1}" for r in group],
                x=[r["end"] - r["start"] for r in group],
                base=[r["start"] for r in group],
                text=[f"J{j + 1}/O{r['operation'] + 1}" for r in group],
                hovertemplate="%{text}<br>Başlangıç: %{base}<br>Süre: %{x}<extra></extra>",
            )
        )
    fig.update_layout(
        title=title,
        barmode="overlay",
        xaxis_title="Benchmark zaman birimi (dakika değil)",
        yaxis_title="Makine",
        height=550,
    )
    fig.write_html(target, include_plotlyjs=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--time-limit", type=float, default=10)
    parser.add_argument(
        "--instances", nargs="+", default=[f"Mk{i:02}" for i in range(1, 11)]
    )
    parser.add_argument("--output", type=Path, default=Path("results/brandimarte"))
    args = parser.parse_args()
    revision = check_upstream()
    args.output.mkdir(parents=True, exist_ok=True)
    metadata = {
        "upstream_commit": revision,
        "python": sys.version,
        "platform": platform.platform(),
        "processor": platform.processor(),
        "ortools": ortools.__version__,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "time_unit": "benchmark",
        "objective": "makespan",
        "seed": 0,
        "workers": 1,
        "time_limit_seconds": args.time_limit,
    }
    summary, failed = [], False
    for name in args.instances:
        if name not in {f"Mk{i:02}" for i in range(1, 11)}:
            parser.error(f"Unknown instance: {name}")
        path = UPSTREAM / f"data/fjsp/brandimarte/{name}.fjs"
        env, jobs, machines = read_instance(path)
        result = {
            "metadata": metadata,
            "input_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "jobs": len(jobs),
            "machines": machines,
            "operations": sum(map(len, jobs)),
        }
        for method, plan in [
            ("job_order_eft", baseline(jobs, machines)),
            ("cp_sat", solve(env, args.time_limit)),
        ]:
            plan["violations"] = (
                validate(jobs, machines, plan["schedule"]) if plan["schedule"] else None
            )
            if plan["schedule"] and plan["makespan"] != max(
                r["end"] for r in plan["schedule"]
            ):
                plan["violations"].append("Objective differs from schedule makespan")
            failed |= plan["violations"] != []
            result[method] = plan
            summary.append(
                dict(
                    instance=name,
                    method=method,
                    jobs=len(jobs),
                    machines=machines,
                    operations=result["operations"],
                    status=plan["status"],
                    makespan=plan["makespan"],
                    best_bound=plan.get("best_bound"),
                    runtime_seconds=round(plan["runtime_seconds"], 4),
                    violations=len(plan["violations"])
                    if plan["violations"] is not None
                    else None,
                )
            )
            if name == "Mk01" and plan["schedule"]:
                gantt(
                    plan["schedule"],
                    f"{name} — {method} — {plan['status']}",
                    args.output / f"{name}_{method}.html",
                )
        (args.output / f"{name}.json").write_text(json.dumps(result, indent=2))
        print(
            name,
            [
                (m, result[m]["status"], result[m]["makespan"], result[m]["violations"])
                for m in ("job_order_eft", "cp_sat")
            ],
            flush=True,
        )
    with (args.output / "summary.csv").open("w") as file:
        writer = csv.DictWriter(file, fieldnames=summary[0].keys())
        writer.writeheader()
        writer.writerows(summary)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()

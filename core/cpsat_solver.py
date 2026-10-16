"""Thin adapter to TU/e's unchanged FJSP parser and CP-SAT model."""

import importlib.util
import math
import subprocess
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "external/job_shop_benchmark"
COMMIT = "d088a26582f5cb79c6b4f2ad94f68ac7c50878cb"
sys.path.insert(0, str(UPSTREAM))

from data.data_parsers.parser_fjsp import parse_fjsp  # noqa: E402
from scheduling_environment.jobShop import JobShop  # noqa: E402
from ortools.sat.python import cp_model  # noqa: E402

# Load the unchanged model file without solution_methods/__init__.py, which
# eagerly imports torch and helpers unrelated to this benchmark.
_spec = importlib.util.spec_from_file_location(
    "upstream_fjsp_model", UPSTREAM / "solution_methods/cp_sat/models/FJSPmodel.py"
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
fjsp_cp_sat_model = _module.fjsp_cp_sat_model


def check_upstream():
    revision = subprocess.check_output(
        ["git", "-C", str(UPSTREAM), "rev-parse", "HEAD"], text=True
    ).strip()
    dirty = subprocess.check_output(
        [
            "git",
            "-C",
            str(UPSTREAM),
            "status",
            "--porcelain",
            "--",
            ".",
            ":(exclude)**/__pycache__/**",
        ],
        text=True,
    ).strip()
    if revision != COMMIT or dirty:
        raise ValueError("Expected clean upstream checkout at pinned commit")
    return revision


def read_instance(path):
    """Strictly validate FJS tokens before comparing with the upstream parser."""
    lines = [
        line.split() for line in Path(path).read_text().splitlines() if line.strip()
    ]
    n_jobs, n_machines = map(int, lines[0][:2])
    if n_jobs <= 0 or n_machines <= 0 or len(lines) != n_jobs + 1:
        raise ValueError("Invalid job/machine count")
    jobs = []
    for line in lines[1:]:
        values = list(map(int, line))
        count, pos, operations = values[0], 1, []
        if count <= 0:
            raise ValueError("Empty job")
        try:
            for _ in range(count):
                alternatives = values[pos]
                pos += 1
                options = {}
                if alternatives <= 0:
                    raise ValueError("Empty alternatives")
                for _ in range(alternatives):
                    machine, duration = values[pos] - 1, values[pos + 1]
                    pos += 2
                    if (
                        machine in options
                        or not 0 <= machine < n_machines
                        or duration <= 0
                    ):
                        raise ValueError("Invalid machine/duration")
                    options[machine] = duration
                operations.append(options)
        except IndexError as exc:
            raise ValueError("Truncated operation") from exc
        if pos != len(values):
            raise ValueError("Extra tokens or incorrect operation count")
        jobs.append(operations)
    env = parse_fjsp(JobShop(), str(Path(path).resolve()), from_absolute_path=True)
    parsed = [[dict(op.processing_times) for op in job.operations] for job in env.jobs]
    if parsed != jobs or env.nr_of_jobs != n_jobs or env.nr_of_machines != n_machines:
        raise ValueError("Upstream parser differs from independently checked input")
    return env, jobs, n_machines


def baseline(jobs, n_machines):
    """Job-order serial list scheduling; choose earliest finish, then machine ID."""
    started = perf_counter()
    available = [0] * n_machines
    rows = []
    for j, operations in enumerate(jobs):
        ready = 0
        for o, options in enumerate(operations):
            end, machine, start = min(
                (max(ready, available[m]) + d, m, max(ready, available[m]))
                for m, d in options.items()
            )
            rows.append(dict(job=j, operation=o, machine=machine, start=start, end=end))
            ready = available[machine] = end
    return {
        "status": "FEASIBLE",
        "makespan": max(r["end"] for r in rows),
        "runtime_seconds": perf_counter() - started,
        "schedule": rows,
    }


def solve(env, time_limit=10.0, seed=0):
    if not math.isfinite(time_limit) or time_limit <= 0:
        raise ValueError("time_limit must be finite and positive")
    is_workshop = hasattr(env, "workshop_scenario")
    if is_workshop:
        from core.workshop_model import workshop_cp_sat_model

        model, variables = workshop_cp_sat_model(env)
    else:
        model, variables = fjsp_cp_sat_model(env)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.random_seed = seed
    solver.parameters.num_search_workers = 1
    status = solver.Solve(model)
    rows = []
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for j, job in enumerate(env.jobs):
            for o, operation in enumerate(job.operations):
                start = solver.Value(variables["starts"][j, o])
                for a, (machine, duration) in enumerate(
                    operation.processing_times.items()
                ):
                    if solver.Value(variables["presences"][j, o, a]):
                        rows.append(
                            dict(
                                job=j,
                                operation=o,
                                machine=machine,
                                start=start,
                                end=start + duration,
                            )
                        )
    extra = {}
    if is_workshop:
        from core.validation import validate_workshop

        violations = validate_workshop(env.workshop_scenario, rows) if rows else None
        if violations:
            raise RuntimeError(f"Invalid workshop schedule: {violations}")
        extra = {
            "violations": violations,
            "time_unit": "minutes",
            "objective": "makespan_under_hard_deadlines",
            "scenario_type": "retrospective"
            if any(
                j.route_source == "retrospective" for j in env.workshop_scenario.jobs
            )
            else "workshop",
            "source_machine_ids": env.source_machine_ids,
            "source_job_ids": env.source_job_ids,
        }
        for row in rows:
            row["source_job_id"] = env.source_job_ids[row["job"]]
            row["source_operation_id"] = env.source_operation_ids[
                row["job"], row["operation"]
            ]
            row["source_machine_id"] = env.source_machine_ids[row["machine"]]
    return {
        **extra,
        "status": solver.StatusName(status),
        "makespan": int(solver.ObjectiveValue()) if rows else None,
        "best_bound": solver.BestObjectiveBound(),
        "runtime_seconds": solver.WallTime(),
        "time_limit_seconds": time_limit,
        "seed": seed,
        "workers": 1,
        "schedule": rows,
    }

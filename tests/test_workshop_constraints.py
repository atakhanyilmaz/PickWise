"""Regression checks for constraints absent from the first WP-2A draft."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from core.cpsat_solver import solve
from core.domain_rules import WorkshopScenario
from core.validation import validate_workshop
from core.workshop_fjsp_builder import build_env


def scenario(*, op=None, now=0, release=0, deadline=None, downtime=()):
    return WorkshopScenario.model_validate(
        {
            "scenario_id": "regression",
            "current_time": now,
            "machines": [
                {
                    "machine_id": 10,
                    "name": "M10",
                    "unavailable_intervals": list(downtime),
                },
                {"machine_id": 30, "name": "M30"},
            ],
            "jobs": [
                {
                    "job_id": 70,
                    "name": "J70",
                    "route_source": "user_approved",
                    "release_time": release,
                    "deadline": deadline,
                    "operations": [
                        op
                        or {
                            "operation_id": 90,
                            "name": "O90",
                            "processing_times": {10: 5},
                        }
                    ],
                }
            ],
        }
    )


def run(s):
    return solve(build_env(s)[0], 2)


def test_completed_real_machine_and_actual_duration_preserved():
    # Actual duration differs from the original estimate. First option is not actual machine.
    s = scenario(
        now=45,
        op={
            "operation_id": 90,
            "name": "done",
            "processing_times": {10: 3, 30: 20},
            "status": "completed",
            "fixed_machine_id": 30,
            "fixed_start": 40,
            "fixed_end": 45,
        },
    )
    original = s.model_dump()
    result = run(s)
    row = result["schedule"][0]
    assert (row["source_machine_id"], row["start"], row["end"]) == (30, 40, 45)
    assert (row["source_job_id"], row["source_operation_id"]) == (70, 90)
    assert result["violations"] == []
    assert s.model_dump() == original


def test_in_progress_remaining_duration_and_machine_occupancy():
    s = scenario(
        now=45,
        op={
            "operation_id": 90,
            "name": "running",
            "processing_times": {10: 99, 30: 20},
            "status": "in_progress",
            "fixed_machine_id": 30,
            "fixed_start": 40,
            "remaining_duration": 7,
        },
    )
    data = s.model_dump()
    data["jobs"].append(
        {
            "job_id": 80,
            "name": "new",
            "operations": [
                {"operation_id": 91, "name": "next", "processing_times": {30: 3}}
            ],
        }
    )
    s = WorkshopScenario.model_validate(data)
    result = run(s)
    a, b = result["schedule"]
    assert (a["source_machine_id"], a["start"], a["end"]) == (30, 40, 52)
    assert b["start"] == 52
    assert validate_workshop(s, result["schedule"]) == []


def test_current_time_release_and_large_horizon():
    result = run(scenario(now=1000, release=1100))
    assert result["status"] == "OPTIMAL"
    assert result["schedule"][0]["start"] == 1100
    assert result["makespan"] == 1105


@pytest.mark.parametrize("deadline, status", [(105, "OPTIMAL"), (104, "INFEASIBLE")])
def test_hard_deadline_feasible_and_proven_infeasible(deadline, status):
    result = run(scenario(now=100, deadline=deadline))
    assert result["status"] == status
    if status == "INFEASIBLE":
        assert result["schedule"] == []
        assert result["makespan"] is None
        assert result["violations"] is None


def test_downtime_blocks_operation_and_supports_touching_endpoints():
    s = scenario(downtime=[(3, 1000)])
    result = run(s)
    assert result["schedule"][0]["start"] == 1000
    s = scenario(downtime=[(5, 1000)])
    assert run(s)["schedule"][0]["end"] == 5


def test_alternative_machine_avoids_downtime():
    s = scenario(
        downtime=[(0, 100)],
        op={
            "operation_id": 90,
            "name": "alternative",
            "processing_times": {10: 5, 30: 8},
        },
    )
    row = run(s)["schedule"][0]
    assert row["source_machine_id"] == 30
    assert row["end"] == 8


def test_fixed_operation_conflicting_with_downtime_is_infeasible():
    s = scenario(
        now=45,
        downtime=[(42, 44)],
        op={
            "operation_id": 90,
            "name": "done",
            "processing_times": {10: 5},
            "status": "completed",
            "fixed_machine_id": 10,
            "fixed_start": 40,
            "fixed_end": 45,
        },
    )
    assert run(s)["status"] == "INFEASIBLE"


def test_global_ids_predecessors_and_initial_available_operations():
    data = scenario().model_dump()
    data["jobs"][0]["operations"].append(
        {"operation_id": 99, "name": "second", "processing_times": {30: 2}}
    )
    other = deepcopy(data["jobs"][0])
    other["job_id"] = 80
    data["jobs"].append(other)
    env, _, _ = build_env(WorkshopScenario.model_validate(data))
    assert [o.operation_id for o in env.operations] == [0, 1, 2, 3]
    assert {
        k: [o.operation_id for o in v]
        for k, v in env.precedence_relations_operations.items()
    } == {0: [], 1: [0], 2: [], 3: [2]}
    assert [[p.operation_id for p in o.predecessors] for o in env.operations] == [
        [],
        [0],
        [],
        [2],
    ]
    assert [o.operation_id for o in env.operations_available_for_scheduling] == [0, 2]


@pytest.mark.parametrize("kind", ["fixed", "now", "release", "deadline", "downtime"])
def test_independent_validator_catches_constraint_violations(kind):
    if kind == "fixed":
        s = scenario(
            now=45,
            op={
                "operation_id": 90,
                "name": "done",
                "processing_times": {10: 5},
                "status": "completed",
                "fixed_machine_id": 10,
                "fixed_start": 40,
                "fixed_end": 45,
            },
        )
        row = dict(job=0, operation=0, machine=0, start=0, end=5)
    else:
        s = scenario(
            now=10 if kind == "now" else 0,
            release=10 if kind == "release" else 0,
            deadline=4 if kind == "deadline" else None,
            downtime=[(2, 4)] if kind == "downtime" else [],
        )
        row = dict(job=0, operation=0, machine=0, start=0, end=5)
    assert validate_workshop(s, [row])


@pytest.mark.parametrize(
    "change",
    [
        {"time_unit": "hours"},
        {"current_time": -1},
        {"unexpected": True},
        {"jobs": []},
        {"machines": []},
    ],
)
def test_invalid_scenario_contract(change):
    data = scenario().model_dump()
    data.update(change)
    with pytest.raises(ValidationError):
        WorkshopScenario.model_validate(data)


@pytest.mark.parametrize(
    "intervals", [[(5, 5)], [(-1, 2)], [(0, 5), (4, 8)], [(0, 1, 2)]]
)
def test_invalid_downtime(intervals):
    with pytest.raises(ValidationError):
        scenario(downtime=intervals)


@pytest.mark.parametrize(
    "op",
    [
        {"status": "completed", "fixed_start": 40, "fixed_end": 45},
        {"status": "in_progress", "fixed_start": 40, "fixed_machine_id": 10},
        {"fixed_start": 0},
        {"processing_times": {10: 2.5}},
    ],
)
def test_missing_actual_machine_remaining_or_invalid_time(op):
    fields = {"operation_id": 90, "name": "op", "processing_times": {10: 5}}
    fields.update(op)
    with pytest.raises(ValidationError):
        scenario(now=45, op=fields)


def test_snapshot_isolated_from_caller_mutation():
    s = scenario()
    env, _, _ = build_env(s)
    s.jobs[0].release_time = 500
    assert solve(env, 1)["schedule"][0]["start"] == 0


def test_retrospective_simulation_explicitly_labelled():
    data = scenario().model_dump()
    data["jobs"][0]["route_source"] = "retrospective"
    s = WorkshopScenario.model_validate(data)
    with pytest.raises(ValueError, match="RETROSPECTIVE"):
        build_env(s)
    result = solve(build_env(s, approved_only=False)[0], 1)
    assert result["scenario_type"] == "retrospective"

"""WP-2A tests: domain_rules + workshop_fjsp_builder.

Run: python -m pytest tests/test_workshop.py -v
"""

import pytest
from pydantic import ValidationError

from core.domain_rules import (
    DurationSource,
    JobModel,
    MachineModel,
    OperationModel,
    OperationStatus,
    RouteSource,
    WorkshopScenario,
)
from core.workshop_fjsp_builder import build_env, demo_scenario
from core.cpsat_solver import solve
from core.validation import validate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _simple_scenario(route_source=RouteSource.USER_APPROVED) -> WorkshopScenario:
    """Two jobs, two machines, no alternatives."""
    return WorkshopScenario(
        scenario_id="test_simple",
        machines=[
            MachineModel(machine_id=0, name="M0"),
            MachineModel(machine_id=1, name="M1"),
        ],
        jobs=[
            JobModel(
                job_id=0,
                name="Job A",
                route_source=route_source,
                operations=[
                    OperationModel(operation_id=0, name="Op0", processing_times={0: 5}),
                    OperationModel(operation_id=1, name="Op1", processing_times={1: 3}),
                ],
            ),
            JobModel(
                job_id=1,
                name="Job B",
                route_source=route_source,
                operations=[
                    OperationModel(operation_id=0, name="Op0", processing_times={0: 4}),
                    OperationModel(operation_id=1, name="Op1", processing_times={1: 6}),
                ],
            ),
        ],
    )


# ---------------------------------------------------------------------------
# domain_rules validation tests
# ---------------------------------------------------------------------------


def test_operation_rejects_zero_duration():
    with pytest.raises(ValidationError, match="greater than 0"):
        OperationModel(
            operation_id=0,
            name="bad",
            processing_times={0: 0},
        )


def test_operation_rejects_empty_processing_times():
    with pytest.raises(ValidationError):
        OperationModel(operation_id=0, name="bad", processing_times={})


def test_job_rejects_empty_operations():
    with pytest.raises(ValidationError):
        JobModel(job_id=0, name="bad", operations=[])


def test_job_rejects_duplicate_operation_ids():
    with pytest.raises(ValidationError, match="unique"):
        JobModel(
            job_id=0,
            name="bad",
            operations=[
                OperationModel(operation_id=0, name="Op0", processing_times={0: 5}),
                OperationModel(operation_id=0, name="Op1", processing_times={1: 3}),
            ],
        )


def test_scenario_rejects_undeclared_machine():
    with pytest.raises(ValidationError, match="undeclared machine_id"):
        WorkshopScenario(
            scenario_id="bad",
            machines=[MachineModel(machine_id=0, name="M0")],
            jobs=[
                JobModel(
                    job_id=0,
                    name="J",
                    operations=[
                        OperationModel(
                            operation_id=0,
                            name="Op",
                            processing_times={99: 5},  # machine 99 not declared
                        )
                    ],
                )
            ],
        )


def test_scenario_rejects_duplicate_machine_ids():
    with pytest.raises(ValidationError, match="unique"):
        WorkshopScenario(
            scenario_id="bad",
            machines=[
                MachineModel(machine_id=0, name="M0"),
                MachineModel(machine_id=0, name="M0_dup"),
            ],
            jobs=_simple_scenario().jobs,
        )


def test_in_progress_operation_requires_fixed_start():
    with pytest.raises(ValidationError, match="fixed_start"):
        OperationModel(
            operation_id=0,
            name="Op",
            processing_times={0: 10},
            status=OperationStatus.IN_PROGRESS,
            fixed_start=None,
        )


def test_completed_operation_requires_both_times():
    with pytest.raises(ValidationError):
        OperationModel(
            operation_id=0,
            name="Op",
            processing_times={0: 10},
            status=OperationStatus.COMPLETED,
            fixed_start=5,
            fixed_end=None,
        )


# ---------------------------------------------------------------------------
# Route source tests
# ---------------------------------------------------------------------------


def test_retrospective_job_blocked_from_solver():
    scenario = _simple_scenario(route_source=RouteSource.RETROSPECTIVE)
    with pytest.raises(ValueError, match="RETROSPECTIVE"):
        build_env(scenario, approved_only=True)


def test_retrospective_job_allowed_when_approved_only_false():
    scenario = _simple_scenario(route_source=RouteSource.RETROSPECTIVE)
    env, jobs, n_machines = build_env(scenario, approved_only=False)
    assert len(jobs) == 2


def test_user_approved_job_passes_solver_gate():
    scenario = _simple_scenario(route_source=RouteSource.USER_APPROVED)
    env, jobs, n_machines = build_env(scenario, approved_only=True)
    assert len(jobs) == 2


def test_jobs_for_solver_excludes_retrospective():
    scenario = WorkshopScenario(
        scenario_id="mixed",
        machines=[MachineModel(machine_id=0, name="M0")],
        jobs=[
            JobModel(
                job_id=0,
                name="Approved",
                route_source=RouteSource.USER_APPROVED,
                operations=[
                    OperationModel(operation_id=0, name="Op", processing_times={0: 5})
                ],
            ),
            JobModel(
                job_id=1,
                name="Retro",
                route_source=RouteSource.RETROSPECTIVE,
                operations=[
                    OperationModel(operation_id=0, name="Op", processing_times={0: 3})
                ],
            ),
        ],
    )
    approved = scenario.jobs_for_solver()
    assert len(approved) == 1
    assert approved[0].job_id == 0


# ---------------------------------------------------------------------------
# build_env structural tests
# ---------------------------------------------------------------------------


def test_build_env_machine_count():
    scenario = _simple_scenario()
    env, jobs, n_machines = build_env(scenario)
    assert n_machines == 2
    assert env.nr_of_machines == 2


def test_build_env_job_count():
    scenario = _simple_scenario()
    env, jobs, n_machines = build_env(scenario)
    assert len(jobs) == 2
    assert env.nr_of_jobs == 2


def test_build_env_alternative_machines():
    """Operation with two eligible machines must list both in env."""
    scenario = WorkshopScenario(
        scenario_id="alt",
        machines=[
            MachineModel(machine_id=0, name="M0"),
            MachineModel(machine_id=1, name="M1"),
        ],
        jobs=[
            JobModel(
                job_id=0,
                name="J",
                operations=[
                    OperationModel(
                        operation_id=0,
                        name="Op",
                        processing_times={0: 10, 1: 15},  # two alternatives
                    )
                ],
            )
        ],
    )
    env, jobs, n_machines = build_env(scenario)
    assert len(jobs[0][0]) == 2  # both machines present


def test_build_env_preserves_machine_dependent_duration():
    scenario = WorkshopScenario(
        scenario_id="dur",
        machines=[
            MachineModel(machine_id=0, name="M0"),
            MachineModel(machine_id=1, name="M1"),
        ],
        jobs=[
            JobModel(
                job_id=0,
                name="J",
                operations=[
                    OperationModel(
                        operation_id=0,
                        name="Op",
                        processing_times={0: 10, 1: 20},
                    )
                ],
            )
        ],
    )
    env, jobs, _ = build_env(scenario)
    assert jobs[0][0][0] == 10
    assert jobs[0][0][1] == 20


# ---------------------------------------------------------------------------
# End-to-end: simple scenario → solver → validator
# ---------------------------------------------------------------------------


def test_simple_scenario_solves_and_validates():
    scenario = _simple_scenario()
    env, jobs, n_machines = build_env(scenario)
    result = solve(env, time_limit=5.0)
    assert result["status"] in ("OPTIMAL", "FEASIBLE")
    violations = validate(jobs, n_machines, result["schedule"])
    assert violations == [], violations


def test_simple_scenario_does_not_mutate_input():
    """build_env must not alter the WorkshopScenario."""
    import copy

    scenario = _simple_scenario()
    original = copy.deepcopy(scenario)
    build_env(scenario)
    assert scenario == original


# ---------------------------------------------------------------------------
# Demo scenario smoke test
# ---------------------------------------------------------------------------


def test_demo_scenario_is_valid():
    scenario = demo_scenario()
    assert scenario.n_jobs == 5
    assert scenario.n_machines == 6


def test_demo_routes_are_labelled_as_assumptions():
    scenario = demo_scenario()
    for job in scenario.jobs:
        assert job.route_source == RouteSource.DEMO_ASSUMPTION


def test_demo_scenario_solves():
    scenario = demo_scenario()
    env, jobs, n_machines = build_env(scenario)
    result = solve(env, time_limit=10.0)
    assert result["status"] in ("OPTIMAL", "FEASIBLE")
    violations = validate(jobs, n_machines, result["schedule"])
    assert violations == [], violations


def test_demo_scenario_duration_source_labelled():
    scenario = demo_scenario()
    for job in scenario.jobs:
        for op in job.operations:
            assert op.duration_source == DurationSource.DEMO_ASSUMPTION

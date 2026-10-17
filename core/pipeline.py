"""Single entry point that chains the existing services: plan → change → solve/validate → dispatch.

Each stage calls an existing, tested service; this module only orders them and adds the
"what runs now" view. Loading and saving plans stay with the caller (SQLite repository),
because saving requires an explicit human approval.
"""

from pydantic import model_validator

from core.domain_rules import Contract, Nonnegative, WorkshopScenario
from core.downtime import DowntimeRequest, DowntimeSimulationResult, simulate_downtime
from core.scenarios import (
    OrderRequest,
    PlanSnapshot,
    ScheduleResult,
    SimulationResult,
    simulate_order,
)


class DispatchItem(Contract):
    job_id: Nonnegative
    job_name: str
    operation_id: Nonnegative
    operation_name: str
    start: Nonnegative
    end: Nonnegative


class MachineStatus(Contract):
    machine_id: Nonnegative
    machine_name: str
    current: DispatchItem | None
    next: DispatchItem | None


class PipelineRequest(Contract):
    """At most one change per run; with no change the baseline plan is only dispatched."""

    order: OrderRequest | None = None
    downtime: DowntimeRequest | None = None
    at_minute: Nonnegative | None = None

    @model_validator(mode="after")
    def one_change(self):
        if self.order is not None and self.downtime is not None:
            raise ValueError("Run one change at a time: an order or a downtime")
        return self


class PipelineResult(Contract):
    baseline: PlanSnapshot
    simulation: SimulationResult | DowntimeSimulationResult | None
    at_minute: Nonnegative
    dispatch: list[MachineStatus]


def dispatch(scenario: WorkshopScenario, result: ScheduleResult, minute: int):
    """For each machine: the operation running at `minute` ([start, end)) and the next one."""
    jobs = {job.job_id: job for job in scenario.jobs}

    def item(row):
        job = jobs[row.source_job_id]
        operation = next(
            op for op in job.operations if op.operation_id == row.source_operation_id
        )
        return DispatchItem(
            job_id=job.job_id,
            job_name=job.name,
            operation_id=operation.operation_id,
            operation_name=operation.name,
            start=row.start,
            end=row.end,
        )

    statuses = []
    for machine in scenario.machines:
        rows = sorted(
            (r for r in result.schedule if r.source_machine_id == machine.machine_id),
            key=lambda r: r.start,
        )
        current = next((r for r in rows if r.start <= minute < r.end), None)
        upcoming = next(
            (r for r in rows if r.start >= minute and r is not current), None
        )
        statuses.append(
            MachineStatus(
                machine_id=machine.machine_id,
                machine_name=machine.name,
                current=item(current) if current else None,
                next=item(upcoming) if upcoming else None,
            )
        )
    return statuses


def run(baseline: PlanSnapshot, request: PipelineRequest) -> PipelineResult:
    """Apply the requested change on a copy of the plan and report what each machine does now.

    The baseline is never modified. If the change has no feasible plan, the dispatch view
    falls back to the baseline so the workshop still sees its current work.
    """
    if request.order is not None:
        simulation = simulate_order(baseline, request.order)
    elif request.downtime is not None:
        simulation = simulate_downtime(baseline, request.downtime)
    else:
        simulation = None

    feasible = simulation is not None and simulation.comparison is not None
    scenario, result = (
        (simulation.scenario, simulation.result)
        if feasible
        else (baseline.scenario, baseline.result)
    )
    minute = (
        request.at_minute if request.at_minute is not None else scenario.current_time
    )
    return PipelineResult(
        baseline=baseline,
        simulation=simulation,
        at_minute=minute,
        dispatch=dispatch(scenario, result, minute),
    )

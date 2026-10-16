"""Typed order simulation and comparison. Never saves or mutates a plan."""

from math import isfinite
from typing import Literal

from pydantic import Field, model_validator

from core.cpsat_solver import solve
from core.domain_rules import (
    Contract,
    JobModel,
    Nonnegative,
    RouteSource,
    WorkshopScenario,
)
from core.validation import validate_workshop
from core.workshop_fjsp_builder import build_env

Status = Literal["OPTIMAL", "FEASIBLE", "INFEASIBLE", "UNKNOWN", "MODEL_INVALID"]


class ScheduleRow(Contract):
    job: Nonnegative
    operation: Nonnegative
    machine: Nonnegative
    start: Nonnegative
    end: Nonnegative
    source_job_id: Nonnegative
    source_operation_id: Nonnegative
    source_machine_id: Nonnegative


class ScheduleResult(Contract):
    status: Status
    makespan: Nonnegative | None
    best_bound: float
    runtime_seconds: float = Field(ge=0, allow_inf_nan=False)
    time_limit_seconds: float = Field(gt=0, allow_inf_nan=False)
    seed: int
    workers: int
    schedule: list[ScheduleRow]
    violations: list[str] | None
    time_unit: Literal["minutes"]
    objective: Literal["makespan_under_hard_deadlines"]
    scenario_type: Literal["workshop", "retrospective"]
    source_machine_ids: list[int]
    source_job_ids: list[int]

    @model_validator(mode="after")
    def status_consistent(self):
        feasible = self.status in ("OPTIMAL", "FEASIBLE")
        if feasible:
            if not self.schedule or self.makespan is None or self.violations != []:
                raise ValueError(
                    "Feasible result requires validated schedule and makespan"
                )
        elif self.schedule or self.makespan is not None or self.violations is not None:
            raise ValueError("No-solution result cannot contain a validated schedule")
        if not isfinite(self.best_bound):
            raise ValueError("Nonfinite bound")
        return self


def check_result(scenario, result):
    """Recheck imported snapshots; do not trust a saved violations=[] claim."""
    if result.source_job_ids != [
        j.job_id for j in scenario.jobs
    ] or result.source_machine_ids != [m.machine_id for m in scenario.machines]:
        raise ValueError("Result source IDs do not match scenario")
    if result.status not in ("OPTIMAL", "FEASIBLE"):
        return
    rows = [row.model_dump() for row in result.schedule]
    errors = validate_workshop(scenario, rows)
    if result.makespan != max(r["end"] for r in rows):
        errors.append("Incorrect makespan")
    for row in result.schedule:
        # Coverage validation above must succeed before indexing.
        if errors:
            break
        job, machine = scenario.jobs[row.job], scenario.machines[row.machine]
        op = job.operations[row.operation]
        if (row.source_job_id, row.source_operation_id, row.source_machine_id) != (
            job.job_id,
            op.operation_id,
            machine.machine_id,
        ):
            errors.append("Incorrect source ID mapping")
    if errors:
        raise ValueError(f"Invalid snapshot schedule: {errors}")


class PlanSnapshot(Contract):
    version_id: str = Field(min_length=1)
    scenario: WorkshopScenario
    result: ScheduleResult

    @model_validator(mode="after")
    def valid_plan(self):
        if self.result.status not in ("OPTIMAL", "FEASIBLE"):
            raise ValueError("Baseline must have a feasible schedule")
        check_result(self.scenario, self.result)
        return self


class JobMetrics(Contract):
    job_id: Nonnegative
    name: str
    completion: Nonnegative
    due_date: Nonnegative | None
    hard_deadline: Nonnegative | None
    tardiness: Nonnegative | None


class PlanMetrics(Contract):
    makespan: Nonnegative
    runtime_seconds: float
    violation_count: Nonnegative
    due_job_count: Nonnegative
    late_job_count: Nonnegative
    total_tardiness: Nonnegative
    jobs: list[JobMetrics]


class JobImpact(Contract):
    job_id: Nonnegative
    name: str
    before_completion: Nonnegative
    after_completion: Nonnegative
    completion_delta: int
    before_tardiness: Nonnegative | None
    after_tardiness: Nonnegative | None
    changed_operations: Nonnegative


class Comparison(Contract):
    before: PlanMetrics
    after: PlanMetrics
    affected_existing_job_count: Nonnegative
    delayed_existing_job_count: Nonnegative
    impacts: list[JobImpact]
    new_job_ids: list[int]


class OrderRequest(Contract):
    baseline_version_id: str = Field(min_length=1)
    scenario_id: str = Field(min_length=1)
    order: JobModel
    preserve_existing_completions: bool = False
    allow_demo: bool = False
    time_limit_seconds: float = Field(default=10, gt=0, allow_inf_nan=False)


class SimulationResult(Contract):
    baseline_version_id: str
    scenario: WorkshopScenario
    result: ScheduleResult
    comparison: Comparison | None
    preserve_existing_completions: bool
    message: str


def status_message(status: Status):
    return {
        "OPTIMAL": "Bu model ve hedef için optimum plan kanıtlandı.",
        "FEASIBLE": "Geçerli plan bulundu; optimum olduğu kanıtlanmadı.",
        "INFEASIBLE": "Bu senaryonun modellenen kısıtları altında uygulanabilir plan yok.",
        "UNKNOWN": "Arama durdu; çözüm elde edilemedi. Bu, senaryonun imkânsız olduğunu kanıtlamaz.",
        "MODEL_INVALID": "Çözücü modeli geçersiz; plan üretilemedi.",
    }[status]


def _run(scenario, time_limit):
    env, _, _ = build_env(scenario)
    result = ScheduleResult.model_validate(solve(env, time_limit))
    check_result(scenario, result)
    return result


def create_snapshot(scenario: WorkshopScenario, version_id: str, time_limit=10):
    scenario = WorkshopScenario.model_validate(scenario.model_dump())
    return PlanSnapshot(
        version_id=version_id, scenario=scenario, result=_run(scenario, time_limit)
    )


def plan_metrics(scenario: WorkshopScenario, result: ScheduleResult):
    check_result(scenario, result)
    if result.status not in ("OPTIMAL", "FEASIBLE"):
        raise ValueError(
            "Cannot calculate completion metrics without a feasible schedule"
        )
    completion = {}
    for row in result.schedule:
        completion[row.source_job_id] = max(
            completion.get(row.source_job_id, 0), row.end
        )
    jobs = [
        JobMetrics(
            job_id=j.job_id,
            name=j.name,
            completion=completion[j.job_id],
            due_date=j.due_date if j.due_date is not None else j.deadline,
            hard_deadline=j.deadline,
            tardiness=max(
                0,
                completion[j.job_id]
                - (j.due_date if j.due_date is not None else j.deadline),
            )
            if j.due_date is not None or j.deadline is not None
            else None,
        )
        for j in scenario.jobs
    ]
    return PlanMetrics(
        makespan=result.makespan,
        runtime_seconds=result.runtime_seconds,
        violation_count=len(result.violations),
        due_job_count=sum(j.due_date is not None for j in jobs),
        late_job_count=sum(j.tardiness is not None and j.tardiness > 0 for j in jobs),
        total_tardiness=sum(j.tardiness or 0 for j in jobs),
        jobs=jobs,
    )


def compare_scenarios(
    baseline: PlanSnapshot, scenario: WorkshopScenario, result: ScheduleResult
):
    baseline = PlanSnapshot.model_validate(baseline.model_dump())
    if (
        scenario.current_time != baseline.scenario.current_time
        or scenario.machines != baseline.scenario.machines
    ):
        raise ValueError("Comparison requires the same time reference and machines")
    for job_id, limit in baseline.scenario.completion_limits.items():
        new_limit = scenario.completion_limits.get(job_id)
        if new_limit is None or new_limit > limit:
            raise ValueError("Existing completion limit was relaxed")
    before, after = (
        plan_metrics(baseline.scenario, baseline.result),
        plan_metrics(scenario, result),
    )
    after_jobs = {j.job_id: j for j in after.jobs}
    new_inputs = {j.job_id: j for j in scenario.jobs}
    before_rows = {
        (r.source_job_id, r.source_operation_id): (r.source_machine_id, r.start, r.end)
        for r in baseline.result.schedule
    }
    after_rows = {
        (r.source_job_id, r.source_operation_id): (r.source_machine_id, r.start, r.end)
        for r in result.schedule
    }
    impacts = []
    for j, original in zip(before.jobs, baseline.scenario.jobs):
        if j.job_id not in new_inputs:
            raise ValueError("Existing job was removed")
        other = new_inputs[j.job_id]
        if original != other:
            raise ValueError("Existing job data changed; not an order-only comparison")
        new = after_jobs[j.job_id]
        changed = sum(
            before_rows[j.job_id, op.operation_id]
            != after_rows[j.job_id, op.operation_id]
            for op in original.operations
        )
        impacts.append(
            JobImpact(
                job_id=j.job_id,
                name=j.name,
                before_completion=j.completion,
                after_completion=new.completion,
                completion_delta=new.completion - j.completion,
                before_tardiness=j.tardiness,
                after_tardiness=new.tardiness,
                changed_operations=changed,
            )
        )
    old_ids = {j.job_id for j in before.jobs}
    return Comparison(
        before=before,
        after=after,
        impacts=impacts,
        affected_existing_job_count=sum(i.changed_operations > 0 for i in impacts),
        delayed_existing_job_count=sum(i.completion_delta > 0 for i in impacts),
        new_job_ids=[j.job_id for j in after.jobs if j.job_id not in old_ids],
    )


def simulate_order(baseline: PlanSnapshot, request: OrderRequest):
    # Revalidate snapshots and requests even if callers mutated Pydantic objects.
    baseline = PlanSnapshot.model_validate(baseline.model_dump())
    request = OrderRequest.model_validate(request.model_dump())
    if request.baseline_version_id != baseline.version_id:
        raise ValueError("Baseline version mismatch")
    order = request.order
    if order.route_source != RouteSource.USER_APPROVED and not (
        request.allow_demo and order.route_source == RouteSource.DEMO_ASSUMPTION
    ):
        raise ValueError(
            "New order requires a user-approved route (or explicit demo mode)"
        )
    if any(op.status != "not_started" for op in order.operations):
        raise ValueError("New order cannot contain started operations")
    if order.job_id in {j.job_id for j in baseline.scenario.jobs}:
        raise ValueError("New order job_id already exists")
    data = baseline.scenario.model_dump()
    if request.scenario_id == data["scenario_id"]:
        raise ValueError("Simulation requires a separate scenario_id")
    data["scenario_id"] = request.scenario_id
    if request.preserve_existing_completions:
        metrics = plan_metrics(baseline.scenario, baseline.result)
        caps = {j.job_id: j.completion for j in metrics.jobs}
        for job in data["jobs"]:
            previous = data["completion_limits"].get(job["job_id"])
            data["completion_limits"][job["job_id"]] = (
                min(previous, caps[job["job_id"]])
                if previous is not None
                else caps[job["job_id"]]
            )
    data["jobs"].append(order.model_dump())
    scenario = WorkshopScenario.model_validate(data)
    result = _run(scenario, request.time_limit_seconds)
    comparison = (
        compare_scenarios(baseline, scenario, result)
        if result.status in ("OPTIMAL", "FEASIBLE")
        else None
    )
    return SimulationResult(
        baseline_version_id=baseline.version_id,
        scenario=scenario,
        result=result,
        comparison=comparison,
        preserve_existing_completions=request.preserve_existing_completions,
        message=status_message(result.status),
    )

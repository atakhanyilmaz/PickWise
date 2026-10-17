"""Add a planned machine outage without changing or saving the baseline."""

from pydantic import Field, model_validator

from core.domain_rules import Contract, Nonnegative, WorkshopScenario
from core.scenarios import (
    Comparison,
    PlanSnapshot,
    ScheduleResult,
    _compare_unchanged_jobs,
    _run,
    plan_metrics,
    status_message,
)


class DowntimeRequest(Contract):
    baseline_version_id: str = Field(min_length=1)
    scenario_id: str = Field(min_length=1)
    machine_id: Nonnegative
    start: Nonnegative
    end: Nonnegative
    reason: str = ""
    preserve_existing_completions: bool = False
    time_limit_seconds: float = Field(default=10, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def positive_interval(self):
        if self.end <= self.start:
            raise ValueError("Downtime end must be after start")
        return self


class DowntimeSimulationResult(Contract):
    baseline_version_id: str
    request: DowntimeRequest
    scenario: WorkshopScenario
    result: ScheduleResult
    comparison: Comparison | None
    message: str


def _union(intervals):
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def compare_downtime(
    baseline: PlanSnapshot, scenario: WorkshopScenario, result: ScheduleResult
):
    baseline = PlanSnapshot.model_validate(baseline.model_dump())
    scenario = WorkshopScenario.model_validate(scenario.model_dump())
    result = ScheduleResult.model_validate(result.model_dump())
    original = baseline.scenario
    if (
        scenario.current_time != original.current_time
        or scenario.time_unit != original.time_unit
        or scenario.time_unit_note != original.time_unit_note
        or scenario.jobs != original.jobs
        or len(scenario.machines) != len(original.machines)
    ):
        raise ValueError(
            "Downtime comparison requires unchanged jobs and time reference"
        )
    for old, new in zip(original.machines, scenario.machines):
        if (old.machine_id, old.name) != (new.machine_id, new.name):
            raise ValueError(
                "Downtime comparison requires the same machine identities/order"
            )
        if any(
            not any(c <= a and b <= d for c, d in new.unavailable_intervals)
            for a, b in old.unavailable_intervals
        ):
            raise ValueError("Existing downtime cannot be removed or shortened")
    return _compare_unchanged_jobs(baseline, scenario, result)


def simulate_downtime(baseline: PlanSnapshot, request: DowntimeRequest):
    baseline = PlanSnapshot.model_validate(baseline.model_dump())
    request = DowntimeRequest.model_validate(request.model_dump())
    if baseline.version_id != request.baseline_version_id:
        raise ValueError("Baseline version mismatch")
    if baseline.scenario.scenario_id == request.scenario_id:
        raise ValueError("Simulation requires a separate scenario_id")
    if request.start < baseline.scenario.current_time:
        raise ValueError("New downtime cannot rewrite the past")
    machines = {m.machine_id: m for m in baseline.scenario.machines}
    if request.machine_id not in machines:
        raise ValueError("Unknown machine_id")
    for job in baseline.scenario.jobs:
        for op in job.operations:
            if op.status == "not_started" or op.fixed_machine_id != request.machine_id:
                continue
            finish = (
                op.fixed_end
                if op.status == "completed"
                else baseline.scenario.current_time + op.remaining_duration
            )
            if op.fixed_start < request.end and request.start < finish:
                raise ValueError(
                    "Downtime intersects a started operation; interruption/resume is not supported"
                )
    data = baseline.scenario.model_dump()
    data["scenario_id"] = request.scenario_id
    data["description"] = (
        data["description"]
        + f"\nPlanlı duruş: M{request.machine_id}, [{request.start}, {request.end}) dakika. {request.reason}"
    ).strip()
    for machine in data["machines"]:
        if machine["machine_id"] == request.machine_id:
            machine["unavailable_intervals"] = _union(
                machine["unavailable_intervals"] + [(request.start, request.end)]
            )
    if request.preserve_existing_completions:
        for job in plan_metrics(baseline.scenario, baseline.result).jobs:
            previous = data["completion_limits"].get(job.job_id)
            data["completion_limits"][job.job_id] = (
                min(previous, job.completion)
                if previous is not None
                else job.completion
            )
    scenario = WorkshopScenario.model_validate(data)
    result = _run(scenario, request.time_limit_seconds)
    comparison = (
        compare_downtime(baseline, scenario, result)
        if result.status in ("OPTIMAL", "FEASIBLE")
        else None
    )
    return DowntimeSimulationResult(
        baseline_version_id=baseline.version_id,
        request=request,
        scenario=scenario,
        result=result,
        comparison=comparison,
        message=status_message(result.status),
    )

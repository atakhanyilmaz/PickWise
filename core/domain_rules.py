"""Validated workshop contracts. Times are integer minutes from scenario t=0."""

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Nonnegative = Annotated[int, Field(strict=True, ge=0)]
Positive = Annotated[int, Field(strict=True, gt=0)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RouteSource(str, Enum):
    RETROSPECTIVE = "retrospective"
    USER_APPROVED = "user_approved"
    DEMO_ASSUMPTION = "demo_assumption"


class DurationSource(str, Enum):
    USER_INPUT = "user_input"
    BENCHMARK = "benchmark"
    TABPFN_ESTIMATE = "tabpfn_estimate"
    HISTORICAL_MEDIAN = "historical_median"
    DEMO_ASSUMPTION = "demo_assumption"


class OperationStatus(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class MachineModel(Contract):
    machine_id: Nonnegative
    name: str
    unavailable_intervals: list[tuple[Nonnegative, Nonnegative]] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def intervals_valid(self):
        intervals = sorted(self.unavailable_intervals)
        if any(end <= start for start, end in intervals):
            raise ValueError("Unavailable interval must have end > start")
        if any(a[1] > b[0] for a, b in zip(intervals, intervals[1:])):
            raise ValueError("Unavailable intervals must not overlap")
        return self


class OperationModel(Contract):
    # Source operation IDs are scoped by job; env IDs are globally unique.
    operation_id: Nonnegative
    name: str
    processing_times: dict[int, Positive]
    duration_source: DurationSource = DurationSource.DEMO_ASSUMPTION
    status: OperationStatus = OperationStatus.NOT_STARTED
    fixed_machine_id: Nonnegative | None = None
    fixed_start: Nonnegative | None = None
    fixed_end: Nonnegative | None = None
    remaining_duration: Positive | None = None

    @model_validator(mode="after")
    def fixed_times_consistent(self):
        if not self.processing_times or any(m < 0 for m in self.processing_times):
            raise ValueError(
                "processing_times requires eligible machines and Duration > 0"
            )
        if self.status == OperationStatus.NOT_STARTED:
            if any(
                v is not None
                for v in (
                    self.fixed_machine_id,
                    self.fixed_start,
                    self.fixed_end,
                    self.remaining_duration,
                )
            ):
                raise ValueError("NOT_STARTED cannot have fixed/remaining fields")
        else:
            if self.fixed_start is None:
                raise ValueError("Started operation requires fixed_start")
            if self.fixed_machine_id not in self.processing_times:
                raise ValueError("Started operation requires eligible fixed_machine_id")
            if self.status == OperationStatus.COMPLETED:
                if self.fixed_end is None or self.fixed_end <= self.fixed_start:
                    raise ValueError("COMPLETED requires fixed_end > fixed_start")
                if self.remaining_duration is not None:
                    raise ValueError("COMPLETED cannot have remaining_duration")
            elif self.fixed_end is not None or self.remaining_duration is None:
                raise ValueError(
                    "IN_PROGRESS requires remaining_duration and no fixed_end"
                )
        return self


class JobModel(Contract):
    job_id: Nonnegative
    name: str
    operations: list[OperationModel] = Field(min_length=1)
    route_source: RouteSource = RouteSource.DEMO_ASSUMPTION
    # Hard deadline. Soft due dates are not implemented by this contract.
    deadline: Nonnegative | None = None
    release_time: Nonnegative = 0

    @model_validator(mode="after")
    def operation_ids_unique(self):
        ids = [op.operation_id for op in self.operations]
        if len(ids) != len(set(ids)):
            raise ValueError("operation_id values must be unique within a job")
        return self

    @property
    def is_route_approved(self):
        return self.route_source == RouteSource.USER_APPROVED

    @property
    def has_in_progress_operations(self):
        return any(op.status == OperationStatus.IN_PROGRESS for op in self.operations)


class WorkshopScenario(Contract):
    scenario_id: str
    description: str = ""
    machines: list[MachineModel] = Field(min_length=1)
    jobs: list[JobModel] = Field(min_length=1)
    current_time: Nonnegative = 0
    time_unit: Literal["minutes"] = "minutes"
    time_unit_note: str = ""

    @model_validator(mode="after")
    def consistent(self):
        for values, label in ((self.machines, "machine"), (self.jobs, "job")):
            ids = [getattr(v, f"{label}_id") for v in values]
            if len(ids) != len(set(ids)):
                raise ValueError(f"{label}_id values must be unique")
        declared = {m.machine_id for m in self.machines}
        for job in self.jobs:
            previous_end = job.release_time
            pending = False
            for op in job.operations:
                if not set(op.processing_times) <= declared:
                    raise ValueError("Operation references undeclared machine_id")
                if op.status == OperationStatus.NOT_STARTED:
                    pending = True
                    continue
                if pending or op.fixed_start < previous_end:
                    raise ValueError(
                        "Started operations must form a consistent route prefix"
                    )
                if op.status == OperationStatus.COMPLETED:
                    if op.fixed_end > self.current_time:
                        raise ValueError("COMPLETED cannot finish after current_time")
                    previous_end = op.fixed_end
                else:
                    if op.fixed_start > self.current_time:
                        raise ValueError("IN_PROGRESS cannot start after current_time")
                    previous_end = self.current_time + op.remaining_duration
                    pending = True
        return self

    @property
    def n_machines(self):
        return len(self.machines)

    @property
    def n_jobs(self):
        return len(self.jobs)

    def jobs_for_solver(self):
        return [j for j in self.jobs if j.route_source != RouteSource.RETROSPECTIVE]

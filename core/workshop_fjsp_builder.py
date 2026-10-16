"""Convert validated workshop input; source IDs remain in env mappings."""

from core.cpsat_solver import JobShop  # initialize pinned upstream imports first
from scheduling_environment.job import Job
from scheduling_environment.machine import Machine
from scheduling_environment.operation import Operation
from core.domain_rules import (
    DurationSource,
    JobModel,
    MachineModel,
    OperationModel,
    OperationStatus,
    RouteSource,
    WorkshopScenario,
)


def build_env(scenario: WorkshopScenario, *, approved_only: bool = True):
    # Revalidate mutable Pydantic data and take an isolated snapshot.
    scenario = WorkshopScenario.model_validate(scenario.model_dump())
    if approved_only and any(
        j.route_source == RouteSource.RETROSPECTIVE for j in scenario.jobs
    ):
        raise ValueError(
            "RETROSPECTIVE routes require user approval; use approved_only=False only for retrospective simulation"
        )
    env = JobShop()
    env.set_instance_name(scenario.scenario_id)
    env.set_nr_of_jobs(scenario.n_jobs)
    env.set_nr_of_machines(scenario.n_machines)
    machine_index = {m.machine_id: i for i, m in enumerate(scenario.machines)}
    for i in range(scenario.n_machines):
        env.add_machine(Machine(i))
    jobs_repr, precedence = [], {}
    source_operations = {}
    for j, source_job in enumerate(scenario.jobs):
        job = Job(j)
        options_list = []
        previous = None
        for o, source_op in enumerate(source_job.operations):
            op = Operation(job, j, len(env.operations))
            if source_op.status == OperationStatus.NOT_STARTED:
                options = {
                    machine_index[m]: d for m, d in source_op.processing_times.items()
                }
            else:
                end = (
                    source_op.fixed_end
                    if source_op.status == OperationStatus.COMPLETED
                    else scenario.current_time + source_op.remaining_duration
                )
                options = {
                    machine_index[source_op.fixed_machine_id]: end
                    - source_op.fixed_start
                }
            for m, duration in options.items():
                op.add_operation_option(m, duration)
            predecessors = [] if previous is None else [previous]
            op.add_predecessors(predecessors)
            precedence[op.operation_id] = predecessors
            source_operations[j, o] = source_op.operation_id
            job.add_operation(op)
            env.add_operation(op)
            options_list.append(options)
            previous = op
        env.add_job(job)
        jobs_repr.append(options_list)
    env.add_precedence_relations_operations(precedence)
    env.update_operations_available_for_scheduling()
    # Explicit scenario metadata consumed by solve(); no reliance on upstream fields.
    env.workshop_scenario = scenario
    env.source_machine_ids = [m.machine_id for m in scenario.machines]
    env.source_job_ids = [j.job_id for j in scenario.jobs]
    env.source_operation_ids = source_operations
    return env, jobs_repr, scenario.n_machines


def demo_scenario() -> WorkshopScenario:
    """Return a small, fully annotated demo scenario.

    All durations are labelled DEMO_ASSUMPTION; the time unit is minutes.
    No actual production data is used here.
    """
    machines = [
        MachineModel(machine_id=0, name="Torna/Freze 1"),
        MachineModel(machine_id=1, name="Torna/Freze 2"),
        MachineModel(machine_id=2, name="Taşlama 1"),
        MachineModel(machine_id=3, name="Taşlama 2"),
        MachineModel(machine_id=4, name="Lazer Markalama"),
        MachineModel(machine_id=5, name="Kalite Kontrol"),
    ]

    def _op(op_id, name, pt, src=DurationSource.DEMO_ASSUMPTION):
        return OperationModel(
            operation_id=op_id,
            name=name,
            processing_times=pt,
            duration_source=src,
        )

    jobs = [
        # J0 — Kablo Kafası: Torna → Taşlama → Lazer → KK
        JobModel(
            job_id=0,
            name="Kablo Kafası",
            route_source=RouteSource.DEMO_ASSUMPTION,
            operations=[
                _op(0, "Tornalama", {0: 45, 1: 52}),
                _op(1, "Taşlama", {2: 30, 3: 38}),
                _op(2, "Lazer Markalama", {4: 12}),
                _op(3, "Kalite Kontrol", {5: 20}),
            ],
        ),
        # J1 — Bilya Somunu: Torna → Taşlama → KK
        JobModel(
            job_id=1,
            name="Bilya Somunu",
            route_source=RouteSource.DEMO_ASSUMPTION,
            operations=[
                _op(0, "Tornalama", {0: 60, 1: 68}),
                _op(1, "Taşlama", {2: 25, 3: 32}),
                _op(2, "Kalite Kontrol", {5: 15}),
            ],
        ),
        # J2 — Düz Dişli: Frezeleme → Taşlama → KK
        JobModel(
            job_id=2,
            name="Düz Dişli",
            route_source=RouteSource.DEMO_ASSUMPTION,
            operations=[
                _op(0, "Frezeleme", {0: 55, 1: 60}),
                _op(1, "Taşlama", {2: 40, 3: 48}),
                _op(2, "Kalite Kontrol", {5: 18}),
            ],
        ),
        # J3 — Zımba Tutucu: Torna → Lazer → KK
        JobModel(
            job_id=3,
            name="Zımba Tutucu",
            route_source=RouteSource.DEMO_ASSUMPTION,
            operations=[
                _op(0, "Tornalama", {0: 35, 1: 40}),
                _op(1, "Lazer Markalama", {4: 10}),
                _op(2, "Kalite Kontrol", {5: 12}),
            ],
        ),
        # J4 — Tapa: Torna → KK  (simple two-step job)
        JobModel(
            job_id=4,
            name="Tapa",
            route_source=RouteSource.DEMO_ASSUMPTION,
            operations=[
                _op(0, "Tornalama", {0: 20, 1: 24}),
                _op(1, "Kalite Kontrol", {5: 8}),
            ],
        ),
    ]

    return WorkshopScenario(
        scenario_id="demo_v1",
        description=(
            "Küçük Türk fason metal atölyesi — 5 iş, 6 makine. "
            "Tüm süreler demo varsayımıdır; gerçek üretim verisi değildir."
        ),
        machines=machines,
        jobs=jobs,
        time_unit="minutes",
        time_unit_note=(
            "Süreler dakika cinsindendir. "
            "Gerçek kayıtlardan doğrulanmamış demo varsayımıdır."
        ),
    )

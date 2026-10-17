"""Typed, allowlisted planning tools. Authority comes from the host, never the model."""

from typing import Literal

from core.domain_rules import Contract, Nonnegative
from core.llm.intake import IntakeResult, confirm_and_simulate
from core.scenarios import PlanMetrics, PlanSnapshot, SimulationResult, plan_metrics
from pydantic import Field


class InspectPlanInput(Contract):
    query: str = Field(min_length=1)


class SimulateOrderInput(Contract):
    intake: IntakeResult
    scenario_id: str = Field(min_length=1)


class WorkloadJob(Contract):
    job_id: Nonnegative
    name: str
    status: Literal["completed", "in_progress", "not_started"]


class Workload(Contract):
    current_time: Nonnegative
    total_job_count: Nonnegative
    unfinished_job_count: Nonnegative
    not_started_job_count: Nonnegative
    operation_counts: dict[str, Nonnegative]
    jobs: list[WorkloadJob]


class InspectionResult(PlanMetrics):
    workload: Workload


def tool_catalog():
    return [
        {
            "name": "inspect_plan",
            "description": "Mevcut iş/sipariş sayısını, bekleyen işleri, bitişleri ve gecikmeleri hesaplayarak gösterir. Yeni sipariş vermeden önce mevcut durumu soran bilgi talepleri de bu araçtır. Planı değiştirmez.",
            "input_schema": InspectPlanInput.model_json_schema(),
            "output_schema": InspectionResult.model_json_schema(),
            "requires_confirmation": False,
        },
        {
            "name": "simulate_order",
            "description": "Yeni siparişin etkisini hesaplar. Önce operasyon, uygun makine, süre ve termin alanları toplanır ve doğrulanır; sonra ayrı insan onayı alınır. Bilgi sormak sipariş ekleme yetkisi değildir. Eksik alan varsa sorulur.",
            "input_schema": SimulateOrderInput.model_json_schema(),
            "output_schema": SimulationResult.model_json_schema(),
            "requires_confirmation": True,
        },
    ]


def routing_catalog():
    """Routing needs capabilities; selected tool arguments are extracted separately."""
    return [
        {k: v for k, v in tool.items() if k not in ("input_schema", "output_schema")}
        for tool in tool_catalog()
    ]


def execute_tool(name, arguments, baseline, *, user_confirmed=False, time_limit=10):
    """No eval, SQL or arbitrary function lookup; only implemented tools run."""
    baseline = PlanSnapshot.model_validate(baseline.model_dump())
    if name == "inspect_plan":
        InspectPlanInput.model_validate(arguments)
        metrics = plan_metrics(baseline.scenario, baseline.result).model_dump()
        counts = {"completed": 0, "in_progress": 0, "not_started": 0}
        jobs = []
        for job in baseline.scenario.jobs:
            for operation in job.operations:
                counts[operation.status] += 1
            status = (
                "completed"
                if all(op.status == "completed" for op in job.operations)
                else "in_progress"
                if any(
                    op.status in ("in_progress", "completed") for op in job.operations
                )
                else "not_started"
            )
            jobs.append({"job_id": job.job_id, "name": job.name, "status": status})
        workload = {
            "current_time": baseline.scenario.current_time,
            "total_job_count": len(jobs),
            "unfinished_job_count": sum(j["status"] != "completed" for j in jobs),
            "not_started_job_count": sum(j["status"] == "not_started" for j in jobs),
            "operation_counts": counts,
            "jobs": jobs,
        }
        return InspectionResult.model_validate(
            {**metrics, "workload": workload}
        ).model_dump()
    if name == "simulate_order":
        inputs = SimulateOrderInput.model_validate(arguments)
        return confirm_and_simulate(
            inputs.intake,
            baseline,
            inputs.scenario_id,
            user_confirmed=user_confirmed,
            time_limit=time_limit,
        )
    raise ValueError(f"Unknown planning tool: {name}")


def render_inspection(inspection):
    """Render authoritative tool values, including what 'waiting' counts mean."""
    workload = inspection["workload"]
    return (
        f"Mevcut planda {workload['total_job_count']} iş var; "
        f"{workload['unfinished_job_count']} iş henüz tamamlanmamış.\n"
        f"Hiç başlamamış iş sayısı: {workload['not_started_job_count']}. "
        f"Başlamamış operasyon sayısı: {workload['operation_counts']['not_started']}.\n"
        f"Planın son bitişi t={inspection['makespan']} dakika; "
        f"mevcut referans zamanı t={workload['current_time']} dakika.\n"
        f"Müşteri terminini aşan iş sayısı: {inspection['late_job_count']}; "
        f"toplam termin gecikmesi: {inspection['total_tardiness']} dakika.\n"
        "Bu değerler yüklü plan içindir; başka kayıtlı siparişler hakkında bilgi içermez."
    )

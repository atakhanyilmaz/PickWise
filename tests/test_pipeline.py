from pathlib import Path

import pytest
from pydantic import ValidationError

from benchmarks.workshop_order_demo import DemoInput
from core.downtime import DowntimeRequest
from core.pipeline import PipelineRequest, run
from core.scenarios import OrderRequest, create_snapshot


@pytest.fixture(scope="module")
def demo():
    return DemoInput.model_validate_json(
        Path("data/examples/order_demo.json").read_text()
    )


@pytest.fixture(scope="module")
def baseline(demo):
    return create_snapshot(demo.baseline, "v1", 5)


def order(baseline, job, preserve=False):
    return OrderRequest(
        baseline_version_id=baseline.version_id,
        scenario_id="pipeline_order",
        order=job,
        preserve_existing_completions=preserve,
        allow_demo=True,
        time_limit_seconds=5,
    )


def by_machine(result):
    return {status.machine_name: status for status in result.dispatch}


def test_dispatch_without_change_uses_current_time(baseline):
    result = run(baseline, PipelineRequest())
    torna1 = by_machine(result)["Torna 1"]
    assert result.simulation is None and result.at_minute == 5
    assert torna1.current.operation_name == "Devam eden işlem"
    assert torna1.next.job_name == "Bekleyen mevcut iş"
    assert by_machine(result)["Torna 2"].current is None


def test_end_is_exclusive(baseline):
    torna1 = by_machine(run(baseline, PipelineRequest(at_minute=10)))["Torna 1"]
    assert torna1.current.job_name == "Bekleyen mevcut iş"


def test_new_order_dispatches_the_simulated_plan(demo, baseline):
    before = baseline.model_dump()
    result = run(
        baseline, PipelineRequest(order=order(baseline, demo.alternative_order))
    )
    assert result.simulation.comparison is not None
    assert by_machine(result)["Torna 2"].current.job_name == "Yeni sipariş"
    assert baseline.model_dump() == before


def test_infeasible_change_falls_back_to_baseline(demo, baseline):
    result = run(
        baseline,
        PipelineRequest(order=order(baseline, demo.new_order, preserve=True)),
    )
    assert result.simulation.result.status == "INFEASIBLE"
    assert all(
        s.current is None or s.current.job_name != "Yeni sipariş"
        for s in result.dispatch
    )


def test_downtime_moves_waiting_work(baseline):
    request = DowntimeRequest(
        baseline_version_id=baseline.version_id,
        scenario_id="pipeline_downtime",
        machine_id=100,
        start=10,
        end=14,
        time_limit_seconds=5,
    )
    result = run(baseline, PipelineRequest(downtime=request, at_minute=12))
    assert result.simulation.comparison is not None
    assert by_machine(result)["Torna 1"].current is None


def test_one_change_at_a_time(demo, baseline):
    downtime = DowntimeRequest(
        baseline_version_id=baseline.version_id,
        scenario_id="x",
        machine_id=100,
        start=10,
        end=12,
    )
    with pytest.raises(ValidationError):
        PipelineRequest(order=order(baseline, demo.new_order), downtime=downtime)

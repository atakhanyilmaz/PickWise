"""Order simulation must preserve baseline state and report only computed effects."""

from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from benchmarks.workshop_order_demo import DemoInput, export_report
from core.domain_rules import JobModel, WorkshopScenario, RouteSource, OperationStatus
from core.scenarios import (
    OrderRequest,
    PlanSnapshot,
    create_snapshot,
    plan_metrics,
    simulate_order,
    status_message,
)
from core.validation import validate_workshop


@pytest.fixture
def demo():
    return DemoInput.model_validate_json(
        Path("data/examples/order_demo.json").read_text()
    )


@pytest.fixture
def baseline(demo):
    return create_snapshot(demo.baseline, "v1", 2)


def request(baseline, order, **options):
    return OrderRequest(
        baseline_version_id=baseline.version_id,
        scenario_id="new_order_simulation",
        order=order,
        allow_demo=True,
        time_limit_seconds=2,
        **options,
    )


def test_new_order_does_not_change_baseline_or_request(demo, baseline):
    original = baseline.model_dump()
    req = request(baseline, demo.new_order)
    original_request = req.model_dump()
    simulated = simulate_order(baseline, req)
    assert baseline.model_dump() == original
    assert req.model_dump() == original_request
    assert simulated.scenario.scenario_id != baseline.scenario.scenario_id
    assert len(baseline.scenario.jobs) == 2
    assert len(simulated.scenario.jobs) == 3


def test_order_effect_and_soft_due_date_metrics(demo, baseline):
    simulated = simulate_order(baseline, request(baseline, demo.new_order))
    assert simulated.result.status == "OPTIMAL"
    c = simulated.comparison
    assert (c.before.makespan, c.after.makespan) == (15, 25)
    existing = next(i for i in c.impacts if i.job_id == 20)
    assert (
        existing.before_completion,
        existing.after_completion,
        existing.completion_delta,
    ) == (15, 25, 10)
    assert (existing.before_tardiness, existing.after_tardiness) == (0, 5)
    assert c.affected_existing_job_count == 1
    assert c.delayed_existing_job_count == 1
    assert c.after.total_tardiness == 5
    assert c.after.late_job_count == 1
    new = next(j for j in c.after.jobs if j.job_id == 30)
    assert new.completion == 20
    assert new.tardiness == 0
    assert simulated.result.violations == []


def test_alternative_machine_preserves_existing_completion(demo, baseline):
    simulated = simulate_order(baseline, request(baseline, demo.alternative_order))
    assert simulated.result.makespan == 17
    assert simulated.comparison.delayed_existing_job_count == 0
    assert simulated.comparison.after.total_tardiness == 0
    row = next(r for r in simulated.result.schedule if r.source_job_id == 30)
    assert row.source_machine_id == 200
    assert row.end == 17


def test_frozen_history_preserved_in_order_simulation(demo, baseline):
    simulated = simulate_order(baseline, request(baseline, demo.new_order))
    before = [r.model_dump() for r in baseline.result.schedule if r.source_job_id == 10]
    after = [r.model_dump() for r in simulated.result.schedule if r.source_job_id == 10]
    assert before == after
    assert [(r["start"], r["end"]) for r in after] == [(0, 3), (3, 10)]
    assert all(r.start >= 5 for r in simulated.result.schedule if r.source_job_id != 10)


def test_completion_protection_is_distinct_from_customer_due_date(demo, baseline):
    simulated = simulate_order(
        baseline, request(baseline, demo.new_order, preserve_existing_completions=True)
    )
    assert simulated.result.status == "INFEASIBLE"
    assert simulated.comparison is None
    assert simulated.result.makespan is None
    assert simulated.scenario.completion_limits == {10: 10, 20: 15}
    assert simulated.scenario.jobs[1].deadline is None
    assert simulated.scenario.jobs[1].due_date == 20
    assert baseline.scenario.completion_limits == {}


def test_completion_protection_can_be_feasible(demo, baseline):
    simulated = simulate_order(
        baseline,
        request(baseline, demo.alternative_order, preserve_existing_completions=True),
    )
    assert simulated.result.status == "OPTIMAL"
    assert simulated.comparison.delayed_existing_job_count == 0


def test_independent_validator_rejects_protected_completion_violation(demo, baseline):
    simulated = simulate_order(baseline, request(baseline, demo.new_order))
    data = simulated.scenario.model_dump()
    data["completion_limits"] = {20: 15}
    scenario = WorkshopScenario.model_validate(data)
    errors = validate_workshop(
        scenario, [r.model_dump() for r in simulated.result.schedule]
    )
    assert any("Completion limit" in error for error in errors)


def test_unknown_produces_no_comparison_or_false_infeasibility(demo, baseline):
    req = request(baseline, demo.new_order)
    req.time_limit_seconds = 1e-9
    simulated = simulate_order(baseline, req)
    assert simulated.result.status == "UNKNOWN"
    assert simulated.comparison is None
    assert "kanıtlamaz" in simulated.message


@pytest.mark.parametrize(
    "status, text",
    [
        ("OPTIMAL", "optimum"),
        ("FEASIBLE", "kanıtlanmadı"),
        ("INFEASIBLE", "kısıtları"),
        ("UNKNOWN", "kanıtlamaz"),
        ("MODEL_INVALID", "geçersiz"),
    ],
)
def test_user_messages_distinguish_solver_status(status, text):
    assert text in status_message(status)


@pytest.mark.parametrize("corruption", ["schedule", "source_id", "makespan"])
def test_saved_baseline_is_revalidated(baseline, corruption):
    data = baseline.model_dump()
    if corruption == "schedule":
        data["result"]["schedule"][0].update(start=1, end=4)
    elif corruption == "source_id":
        data["result"]["schedule"][0]["source_job_id"] = 999
    else:
        data["result"]["makespan"] = 999
    with pytest.raises(ValidationError):
        PlanSnapshot.model_validate(data)


@pytest.mark.parametrize(
    "kind",
    ["duplicate", "unknown_machine", "retro", "unapproved_demo", "version", "started"],
)
def test_invalid_order_requests(demo, baseline, kind):
    req = request(baseline, demo.new_order)
    if kind == "duplicate":
        req.order.job_id = 20
    elif kind == "unknown_machine":
        req.order.operations[0].processing_times = {999: 10}
    elif kind == "retro":
        req.order.route_source = RouteSource.RETROSPECTIVE
    elif kind == "unapproved_demo":
        req.allow_demo = False
    elif kind == "version":
        req.baseline_version_id = "wrong"
    else:
        req.order.operations[0].status = OperationStatus.IN_PROGRESS
        req.order.operations[0].fixed_machine_id = 100
        req.order.operations[0].fixed_start = 5
        req.order.operations[0].remaining_duration = 10
    with pytest.raises(ValueError):
        simulate_order(baseline, req)


def test_missing_or_unsupported_order_fields_rejected():
    with pytest.raises(ValidationError):
        JobModel.model_validate({"job_id": 30, "name": "Eksik sipariş"})
    with pytest.raises(ValidationError):
        OrderRequest.model_validate(
            {
                "baseline_version_id": "v1",
                "scenario_id": "s2",
                "free_text": "yarın sabah sipariş ekle",
            }
        )


def test_no_due_date_jobs_excluded_and_hard_deadline_counted(demo):
    data = demo.baseline.model_dump()
    data["jobs"][0]["due_date"] = None
    data["jobs"][1]["due_date"] = None
    data["jobs"][1]["deadline"] = 30
    snapshot = create_snapshot(WorkshopScenario.model_validate(data), "v1", 2)
    metrics = plan_metrics(snapshot.scenario, snapshot.result)
    assert metrics.due_job_count == 1
    assert metrics.jobs[0].tardiness is None
    assert metrics.jobs[1].tardiness == 0


def test_json_roundtrip_reuses_validated_baseline(baseline, demo):
    loaded = PlanSnapshot.model_validate_json(baseline.model_dump_json())
    assert simulate_order(loaded, request(loaded, demo.new_order)).result.makespan == 25


def test_offline_report_exports_no_fake_chart_when_infeasible(tmp_path, baseline, demo):
    original = deepcopy(baseline.model_dump())
    simulated = simulate_order(
        baseline, request(baseline, demo.new_order, preserve_existing_completions=True)
    )
    export_report(baseline, {"Korumalı": simulated}, tmp_path)
    html = (tmp_path / "comparison.html").read_text()
    assert "Başlangıç planı korunur" in html
    assert "<script src=" not in html
    assert "INFEASIBLE" in (tmp_path / "summary.csv").read_text()
    assert (
        PlanSnapshot.model_validate_json(
            (tmp_path / "baseline.json").read_text()
        ).version_id
        == baseline.version_id
    )
    assert baseline.model_dump() == original


def test_existing_completion_caps_not_relaxed(demo):
    data = demo.baseline.model_dump()
    data["completion_limits"] = {20: 15}
    capped = create_snapshot(WorkshopScenario.model_validate(data), "v_capped", 2)
    result = simulate_order(capped, request(capped, demo.new_order))
    assert result.result.status == "INFEASIBLE"
    assert result.scenario.completion_limits == {20: 15}


def test_arbitrary_job_edits_are_not_reported_as_order_effect(demo, baseline):
    from core.scenarios import compare_scenarios

    data = demo.baseline.model_dump()
    data["jobs"][1]["due_date"] = 99
    changed = create_snapshot(WorkshopScenario.model_validate(data), "changed", 2)
    with pytest.raises(ValueError, match="Existing job data changed"):
        compare_scenarios(baseline, changed.scenario, changed.result)

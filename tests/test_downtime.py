"""Planned outages preserve history, versions and existing schedule constraints."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import core.downtime as downtime
from core.domain_rules import WorkshopScenario
from core.scenarios import ScheduleResult, create_snapshot
from core.validation import validate_workshop


@pytest.fixture
def baseline():
    raw = json.loads(Path("data/examples/order_demo.json").read_text())
    return create_snapshot(WorkshopScenario.model_validate(raw["baseline"]), "v1", 2)


def request(**changes):
    return downtime.DowntimeRequest.model_validate(
        {
            "baseline_version_id": "v1",
            "scenario_id": "planned-outage",
            "machine_id": 100,
            "start": 10,
            "end": 20,
            "time_limit_seconds": 2,
        }
        | changes
    )


def test_downtime_delay_tardiness_and_input_preservation(baseline):
    req = request()
    before, original_request = baseline.model_dump(), req.model_dump()
    result = downtime.simulate_downtime(baseline, req)
    assert baseline.model_dump() == before and req.model_dump() == original_request
    assert result.result.status == "OPTIMAL"
    assert result.comparison.before.makespan == 15
    assert result.comparison.after.makespan == 25
    assert result.comparison.after.total_tardiness == 5
    assert result.comparison.delayed_existing_job_count == 1
    assert result.comparison.new_job_ids == []

    def frozen(r):
        return [x.model_dump() for x in r.schedule if x.source_job_id == 10]

    assert frozen(result.result) == frozen(baseline.result)
    assert (
        validate_workshop(
            result.scenario, [r.model_dump() for r in result.result.schedule]
        )
        == []
    )


def test_alternative_machine_is_selected_from_existing_eligibility(baseline):
    scenario = baseline.scenario.model_dump()
    scenario["jobs"][1]["operations"][0]["processing_times"][200] = 7
    base = create_snapshot(WorkshopScenario.model_validate(scenario), "v1", 2)
    result = downtime.simulate_downtime(base, request())
    row = next(r for r in result.result.schedule if r.source_job_id == 20)
    assert (row.source_machine_id, row.start, row.end) == (200, 10, 17)
    assert result.comparison.after.total_tardiness == 0


def test_preserving_completions_can_make_outage_infeasible(baseline):
    result = downtime.simulate_downtime(
        baseline, request(preserve_existing_completions=True)
    )
    assert result.result.status == "INFEASIBLE"
    assert result.comparison is None
    assert result.scenario.completion_limits == {10: 10, 20: 15}
    assert baseline.scenario.completion_limits == {}


def test_outage_at_operation_end_obeys_half_open_intervals(baseline):
    result = downtime.simulate_downtime(baseline, request(start=15, end=20))
    assert result.result.makespan == 15
    assert result.comparison.delayed_existing_job_count == 0


def test_hard_deadline_cannot_be_silently_relaxed(baseline):
    data = baseline.scenario.model_dump()
    data["jobs"][1]["deadline"] = 20
    base = create_snapshot(WorkshopScenario.model_validate(data), "v1", 2)
    result = downtime.simulate_downtime(base, request())
    assert result.result.status == "INFEASIBLE"
    assert result.scenario.jobs[1].deadline == 20


def test_overlapping_existing_outages_are_unioned_without_mutation(baseline):
    data = baseline.scenario.model_dump()
    data["machines"][0]["unavailable_intervals"] = [(15, 18), (20, 22)]
    base = create_snapshot(WorkshopScenario.model_validate(data), "v1", 2)
    result = downtime.simulate_downtime(base, request(start=17, end=20))
    assert result.scenario.machines[0].unavailable_intervals == [(15, 22)]
    assert base.scenario.machines[0].unavailable_intervals == [(15, 18), (20, 22)]


@pytest.mark.parametrize(
    "changes,message",
    [
        ({"start": 5, "end": 8}, "interruption/resume"),
        ({"start": 4}, "past"),
        ({"machine_id": 999}, "Unknown machine"),
        ({"baseline_version_id": "old"}, "version mismatch"),
        ({"scenario_id": "workshop_demo_base"}, "separate scenario"),
    ],
)
def test_invalid_or_unsupported_outage_rejected(baseline, changes, message):
    with pytest.raises(ValueError, match=message):
        downtime.simulate_downtime(baseline, request(**changes))


@pytest.mark.parametrize(
    "changes", [{"end": 10}, {"start": True}, {"end": -1}, {"unknown": 1}]
)
def test_invalid_request_fields_rejected(changes):
    with pytest.raises(ValidationError):
        request(**changes)


def test_unknown_is_not_reported_as_infeasible(baseline, monkeypatch):
    data = baseline.result.model_dump()
    data.update(status="UNKNOWN", schedule=[], makespan=None, violations=None)
    monkeypatch.setattr(
        downtime, "_run", lambda *args: ScheduleResult.model_validate(data)
    )
    result = downtime.simulate_downtime(baseline, request())
    assert result.comparison is None
    assert "kanıtlamaz" in result.message


def test_comparison_rejects_changed_jobs_or_relaxed_outages(baseline):
    result = downtime.simulate_downtime(baseline, request())
    data = result.scenario.model_dump()
    data["jobs"][1]["due_date"] = 999
    with pytest.raises(ValueError, match="unchanged jobs"):
        downtime.compare_downtime(
            baseline, WorkshopScenario.model_validate(data), result.result
        )
    base = create_snapshot(result.scenario, "v2", 2)
    data = result.scenario.model_dump()
    data["machines"][0]["unavailable_intervals"] = []
    with pytest.raises(ValueError, match="removed or shortened"):
        downtime.compare_downtime(
            base, WorkshopScenario.model_validate(data), result.result
        )


def test_comparison_rejects_relaxed_existing_completion_cap(baseline):
    data = baseline.scenario.model_dump()
    data["completion_limits"] = {20: 30}
    base = create_snapshot(WorkshopScenario.model_validate(data), "v1", 2)
    result = downtime.simulate_downtime(base, request())
    data = result.scenario.model_dump()
    data["completion_limits"] = {}
    with pytest.raises(ValueError, match="relaxed"):
        downtime.compare_downtime(
            base, WorkshopScenario.model_validate(data), result.result
        )


def test_downtime_is_saved_only_as_explicit_new_sqlite_version(baseline, tmp_path):
    from datetime import datetime

    from core.plan_contract import StoredPlanVersion
    from core.scenarios import PlanSnapshot
    from core.sqlite_repository import SQLitePlanRepository

    repo = SQLitePlanRepository(tmp_path / "plans.sqlite3")
    repo.initialize()
    record = StoredPlanVersion(
        plan_id="demo",
        approved_by="synthetic-test",
        approved_at=datetime.fromisoformat("2026-10-17T12:00:00+03:00"),
        snapshot=baseline,
    )
    repo.save_approved_version(record, expected_current_version_id=None)
    result = downtime.simulate_downtime(repo.load_current("demo").snapshot, request())
    assert repo.load_current("demo") == record
    next_record = StoredPlanVersion(
        **record.model_dump(exclude={"snapshot", "parent_version_id"}),
        parent_version_id="v1",
        snapshot=PlanSnapshot(
            version_id="v2", scenario=result.scenario, result=result.result
        ),
    )
    repo.save_approved_version(next_record, expected_current_version_id="v1")
    assert repo.load_current("demo") == next_record
    assert repo.load_version("demo", "v1") == record

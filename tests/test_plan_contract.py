"""Persistence boundary checks; these do not claim SQLite integration."""

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.domain_rules import WorkshopScenario
from core.plan_contract import StoredPlanVersion
from core.scenarios import create_snapshot


@pytest.fixture
def record():
    demo = json.loads(Path("data/examples/order_demo.json").read_text())
    snapshot = create_snapshot(
        WorkshopScenario.model_validate(demo["baseline"]), "v1", 2
    )
    return StoredPlanVersion(
        plan_id="synthetic-workshop",
        approved_by="demo-user",
        approved_at=datetime.fromisoformat("2026-10-17T12:00:00+03:00"),
        snapshot=snapshot,
    )


def test_json_roundtrip_preserves_keys_order_and_frozen_history(record):
    loaded = StoredPlanVersion.model_validate_json(record.model_dump_json())
    assert loaded.model_dump() == record.model_dump()
    assert loaded.snapshot.scenario.jobs[0].operations[0].processing_times == {100: 3}
    assert [m.machine_id for m in loaded.snapshot.scenario.machines] == [100, 200]
    history = [
        (r.source_operation_id, r.source_machine_id, r.start, r.end)
        for r in loaded.snapshot.result.schedule
        if r.source_job_id == 10
    ]
    assert history == [(1, 100, 0, 3), (2, 100, 3, 10)]


def test_corrupted_json_schedule_rejected_despite_empty_violations(record):
    payload = record.model_dump(mode="json")
    payload["snapshot"]["result"]["schedule"][0]["end"] += 1
    assert payload["snapshot"]["result"]["violations"] == []
    with pytest.raises(ValidationError, match="Invalid snapshot schedule"):
        StoredPlanVersion.model_validate_json(json.dumps(payload))


def test_mutated_snapshot_instance_rechecked(record):
    snapshot = deepcopy(record.snapshot)
    snapshot.result.schedule[0].source_machine_id = 999
    with pytest.raises(ValidationError):
        StoredPlanVersion(**record.model_dump(exclude={"snapshot"}), snapshot=snapshot)


@pytest.mark.parametrize("route", ["user_proposed", "retrospective"])
def test_unapproved_operational_routes_rejected(record, route):
    payload = record.model_dump()
    payload["snapshot"]["scenario"]["jobs"][0]["route_source"] = route
    with pytest.raises(ValidationError, match="approved or explicit demo"):
        StoredPlanVersion.model_validate(payload)


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": 2},
        {"approved_at": "2026-10-17T12:00:00"},
        {"approved_by": "  "},
        {"plan_id": ""},
        {"parent_version_id": "v1"},
        {"unexpected": "ignored?"},
    ],
)
def test_invalid_storage_metadata_rejected(record, changes):
    with pytest.raises(ValidationError):
        StoredPlanVersion.model_validate(record.model_dump() | changes)


def test_no_solution_cannot_be_an_approved_plan(record):
    payload = record.model_dump()
    payload["snapshot"]["result"].update(
        status="UNKNOWN", schedule=[], makespan=None, violations=None
    )
    with pytest.raises(ValidationError, match="Baseline must have a feasible"):
        StoredPlanVersion.model_validate(payload)

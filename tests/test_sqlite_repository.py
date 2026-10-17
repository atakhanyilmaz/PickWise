"""Actual SQLite persistence, rollback, corruption and competing writers."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from threading import Barrier

import pytest
from pydantic import ValidationError

from core.domain_rules import WorkshopScenario
from core.plan_contract import PlanVersionConflict, StoredPlanVersion
from core.scenarios import PlanSnapshot, OrderRequest, create_snapshot, simulate_order
from core.sqlite_repository import PlanStorageError, SQLitePlanRepository


@pytest.fixture
def record():
    demo = json.loads(Path("data/examples/order_demo.json").read_text())
    scenario = WorkshopScenario.model_validate(demo["baseline"])
    scenario.machines[1].unavailable_intervals = [(30, 40)]
    scenario.completion_limits = {10: 10}
    return StoredPlanVersion(
        plan_id="demo",
        approved_by="demo-user",
        approved_at=datetime.fromisoformat("2026-10-17T12:00:00+03:00"),
        snapshot=create_snapshot(scenario, "v1", 2),
    )


@pytest.fixture
def repo(tmp_path):
    repository = SQLitePlanRepository(tmp_path / "plans.sqlite3")
    repository.initialize()
    return repository


def child(record, version="v2"):
    payload = record.model_dump()
    payload["parent_version_id"] = record.snapshot.version_id
    payload["snapshot"]["version_id"] = version
    return StoredPlanVersion.model_validate(payload)


def test_roundtrip_including_optional_tables_and_frozen_history(repo, record):
    repo.save_approved_version(record, expected_current_version_id=None)
    repo.initialize()  # reopening must not erase plans
    assert repo.load_current("demo") == record
    assert repo.load_version("demo", "v1") == record
    with sqlite3.connect(repo.path) as conn:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert (
            conn.execute(
                "SELECT count(*) FROM plan_machine_unavailable_intervals"
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute("SELECT count(*) FROM plan_job_completion_limits").fetchone()[
                0
            ]
            == 1
        )


def test_order_simulation_is_explicitly_saved_as_a_new_version(repo, record):
    repo.save_approved_version(record, expected_current_version_id=None)
    demo = json.loads(Path("data/examples/order_demo.json").read_text())
    baseline = repo.load_current("demo").snapshot
    simulation = simulate_order(
        baseline,
        OrderRequest(
            baseline_version_id="v1",
            scenario_id="added-order",
            order=demo["alternative_order"],
            allow_demo=True,
            time_limit_seconds=2,
        ),
    )
    assert repo.load_current("demo") == record  # simulation has no storage side effect
    payload = record.model_dump()
    payload.update(
        parent_version_id="v1",
        snapshot=PlanSnapshot(
            version_id="v2",
            scenario=simulation.scenario,
            result=simulation.result,
        ).model_dump(),
    )
    selected = StoredPlanVersion.model_validate(payload)
    repo.save_approved_version(selected, expected_current_version_id="v1")
    assert repo.load_version("demo", "v1") == record
    assert repo.load_current("demo") == selected
    assert len(selected.snapshot.scenario.jobs) == 3


def test_stale_parent_and_duplicate_rejected_without_state_changes(repo, record):
    repo.save_approved_version(record, expected_current_version_id=None)
    with pytest.raises(PlanVersionConflict):
        repo.save_approved_version(child(record), expected_current_version_id=None)
    with pytest.raises(PlanVersionConflict):
        repo.save_approved_version(record, expected_current_version_id="v1")
    with pytest.raises(PlanVersionConflict):
        repo.save_approved_version(child(record), expected_current_version_id="wrong")
    assert repo.load_current("demo") == record


def test_two_connections_one_winner(repo, record):
    repo.save_approved_version(record, expected_current_version_id=None)
    barrier = Barrier(2)

    def attempt(version):
        other = SQLitePlanRepository(repo.path)
        barrier.wait(timeout=5)
        try:
            other.save_approved_version(
                child(record, version), expected_current_version_id="v1"
            )
            return "saved"
        except PlanVersionConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, ["v2a", "v2b"]))
    assert sorted(outcomes) == ["conflict", "saved"]
    assert repo.load_current("demo").snapshot.version_id in ("v2a", "v2b")
    assert repo.load_version("demo", "v1") == record
    with sqlite3.connect(repo.path) as conn:
        assert conn.execute("SELECT count(*) FROM plan_versions").fetchone()[0] == 2


@pytest.mark.parametrize("initial", [True, False])
def test_failure_after_sealing_rolls_back_everything(repo, record, initial):
    if not initial:
        repo.save_approved_version(record, expected_current_version_id=None)
    with sqlite3.connect(repo.path) as conn:
        conn.executescript("""CREATE TRIGGER test_write_failure BEFORE UPDATE ON plans
        BEGIN SELECT RAISE(ABORT, 'injected failure'); END;""")
    with pytest.raises(sqlite3.IntegrityError, match="injected failure"):
        repo.save_approved_version(
            record if initial else child(record),
            expected_current_version_id=None if initial else "v1",
        )
    with sqlite3.connect(repo.path) as conn:
        count = 0 if initial else 1
        for table in ("plans", "plan_versions", "plan_scenarios", "schedule_results"):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == count
    if initial:
        with pytest.raises(KeyError):
            repo.load_current("demo")
    else:
        assert repo.load_current("demo") == record
        with pytest.raises(KeyError):
            repo.load_version("demo", "v2")


def test_corrupted_json_schedule_is_not_trusted(repo, record):
    repo.save_approved_version(record, expected_current_version_id=None)
    data = record.snapshot.model_dump(mode="json")
    data["result"]["schedule"][0]["end"] += 1
    # Emulate an externally modified/corrupt database, bypassing SQL immutability.
    with sqlite3.connect(repo.path) as conn:
        conn.execute("DROP TRIGGER plan_versions_seal_once")
        conn.execute("UPDATE plan_versions SET snapshot_json=?", (json.dumps(data),))
    with pytest.raises(ValidationError):
        repo.load_current("demo")


def test_relational_corruption_rejected_even_if_json_is_valid(repo, record):
    repo.save_approved_version(record, expected_current_version_id=None)
    with sqlite3.connect(repo.path) as conn:
        conn.execute("DROP TRIGGER plan_jobs_immutable_update")
        conn.execute("UPDATE plan_jobs SET name='different'")
    with pytest.raises(PlanStorageError, match="plan_jobs"):
        repo.load_version("demo", "v1")


def test_mutated_input_rejected_before_writing(repo, record):
    record.snapshot.result.schedule[0].end += 1
    with pytest.raises(ValidationError):
        repo.save_approved_version(record, expected_current_version_id=None)
    with pytest.raises(KeyError):
        repo.load_current("demo")


def test_missing_record_and_incompatible_schema(repo, tmp_path):
    with pytest.raises(KeyError):
        repo.load_version("unknown", "v1")
    with pytest.raises(KeyError):
        repo.load_current("unknown")
    path = tmp_path / "unrelated.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE unrelated(id INTEGER)")
    with pytest.raises(PlanStorageError):
        SQLitePlanRepository(path).initialize()


def test_schema_rejects_missing_snapshot_version(repo):
    with sqlite3.connect(repo.path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("INSERT INTO plans(plan_id) VALUES ('demo')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("""INSERT INTO plan_versions
                (plan_id,version_id,schema_version,approved_by,approved_at,snapshot_json)
                VALUES ('demo','v1',1,'user','2026-10-17T12:00:00+03:00','{}')""")

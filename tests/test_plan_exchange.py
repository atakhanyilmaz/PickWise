"""Git seed exchange checks with real temporary SQLite databases."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.domain_rules import WorkshopScenario
from core.plan_contract import StoredPlanVersion
from core.plan_exchange import (
    PlanSeedBundle,
    PlanSeedConflict,
    import_seed,
    load_seed,
    publish_seed,
)
from core.scenarios import create_snapshot
from core.sqlite_repository import SQLitePlanRepository


@pytest.fixture
def record():
    demo = json.loads(Path("data/examples/order_demo.json").read_text())
    scenario = WorkshopScenario.model_validate(demo["baseline"])
    return StoredPlanVersion(
        plan_id="demo",
        approved_by="demo-user",
        approved_at=datetime.fromisoformat("2026-10-17T12:00:00+03:00"),
        snapshot=create_snapshot(scenario, "v1", 2),
    )


def child(record, version, *, approved_by=None):
    payload = record.model_dump()
    payload["parent_version_id"] = record.snapshot.version_id
    payload["snapshot"]["version_id"] = version
    if approved_by is not None:
        payload["approved_by"] = approved_by
    return StoredPlanVersion.model_validate(payload)


def repository(path):
    repo = SQLitePlanRepository(path)
    repo.initialize()
    return repo


def save_chain(repo, records):
    expected = None
    for item in records:
        repo.save_approved_version(item, expected_current_version_id=expected)
        expected = item.snapshot.version_id


def test_publish_is_deterministic_immutable_and_includes_ancestry(tmp_path, record):
    repo = repository(tmp_path / "source.sqlite3")
    v2 = child(record, "v2")
    save_chain(repo, [record, v2])
    seed = tmp_path / "seed.json"

    assert publish_seed(repo, seed, "demo") == ["v1", "v2"]
    first = seed.read_text(encoding="utf-8")
    assert publish_seed(repo, seed, "demo") == []
    assert seed.read_text(encoding="utf-8") == first
    bundle = load_seed(seed)
    assert bundle.plans["demo"].current_version_id == "v2"
    assert [r.snapshot.version_id for r in bundle.plans["demo"].ordered_versions()] == [
        "v1",
        "v2",
    ]

    changed = child(record, "v2", approved_by="other-user")
    raw = bundle.model_dump(mode="json")
    raw["plans"]["demo"]["versions"]["v2"] = changed.model_dump(mode="json")
    seed.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(PlanSeedConflict, match="different content"):
        publish_seed(repo, seed, "demo")


def test_import_full_chain_and_repeat_is_idempotent(tmp_path, record):
    source = repository(tmp_path / "source.sqlite3")
    v2 = child(record, "v2")
    save_chain(source, [record, v2])
    seed = tmp_path / "seed.json"
    publish_seed(source, seed, "demo")
    target = repository(tmp_path / "target.sqlite3")

    preview = import_seed(target, seed, dry_run=True)
    assert preview.imported == {"demo": ["v1", "v2"]}
    with pytest.raises(KeyError):
        target.load_current("demo")
    result = import_seed(target, seed)
    assert result.imported == {"demo": ["v1", "v2"]}
    assert target.load_current("demo") == v2
    repeated = import_seed(target, seed)
    assert repeated.imported == {}
    assert repeated.up_to_date == ["demo"]


def test_seed_rejects_tampering_and_branching(record):
    v2a, v2b = child(record, "v2a"), child(record, "v2b")
    branch = {
        "seed_schema_version": 1,
        "plans": {
            "demo": {
                "current_version_id": "v2a",
                "versions": {
                    "v1": record.model_dump(mode="json"),
                    "v2a": v2a.model_dump(mode="json"),
                    "v2b": v2b.model_dump(mode="json"),
                },
            }
        },
    }
    with pytest.raises(ValidationError, match="cannot branch"):
        PlanSeedBundle.model_validate(branch)

    branch["plans"]["demo"]["versions"].pop("v2b")
    branch["plans"]["demo"]["versions"]["v1"]["snapshot"]["result"][
        "schedule"
    ][0]["end"] += 1
    with pytest.raises(ValidationError, match="Invalid snapshot schedule"):
        PlanSeedBundle.model_validate(branch)


def test_local_and_shared_branches_are_rejected_without_changes(tmp_path, record):
    shared_repo = repository(tmp_path / "shared.sqlite3")
    shared_v2 = child(record, "shared-v2")
    save_chain(shared_repo, [record, shared_v2])
    seed = tmp_path / "seed.json"
    publish_seed(shared_repo, seed, "demo")

    local_repo = repository(tmp_path / "local.sqlite3")
    local_v2 = child(record, "local-v2")
    save_chain(local_repo, [record, local_v2])
    with pytest.raises(PlanSeedConflict, match="histories diverged"):
        import_seed(local_repo, seed)
    assert local_repo.load_current("demo") == local_v2
    with pytest.raises(KeyError):
        local_repo.load_version("demo", "shared-v2")


def test_import_rolls_back_complete_missing_tail_on_database_error(tmp_path, record):
    source = repository(tmp_path / "source.sqlite3")
    v2, v3 = child(record, "v2"), child(child(record, "v2"), "v3")
    save_chain(source, [record, v2, v3])
    seed = tmp_path / "seed.json"
    publish_seed(source, seed, "demo")

    target = repository(tmp_path / "target.sqlite3")
    save_chain(target, [record])
    with sqlite3.connect(target.path) as conn:
        conn.executescript("""CREATE TRIGGER fail_v3 BEFORE INSERT ON plan_versions
        WHEN NEW.version_id = 'v3'
        BEGIN SELECT RAISE(ABORT, 'injected import failure'); END;""")
    with pytest.raises(sqlite3.IntegrityError, match="injected import failure"):
        import_seed(target, seed)
    assert target.load_current("demo") == record
    with pytest.raises(KeyError):
        target.load_version("demo", "v2")

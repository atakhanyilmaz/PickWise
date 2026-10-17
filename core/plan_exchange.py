"""Validated Git exchange for approved plan versions.

The JSON seed is a collaboration artifact, not a live database. Draft
simulations never enter it, and Git operations remain the caller's job.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from core.domain_rules import Contract
from core.plan_contract import Identifier, PlanRepository, StoredPlanVersion


class PlanSeedConflict(ValueError):
    """The shared and local histories cannot be combined without a decision."""


class SeedPlan(Contract):
    current_version_id: Identifier
    versions: dict[str, StoredPlanVersion] = Field(min_length=1)

    @model_validator(mode="after")
    def linear_history(self):
        for key, record in self.versions.items():
            if key != record.snapshot.version_id:
                raise ValueError("Seed version key differs from snapshot version")
        roots = [
            version_id
            for version_id, record in self.versions.items()
            if record.parent_version_id is None
        ]
        if len(roots) != 1:
            raise ValueError("A shared plan must have exactly one root version")
        children: dict[str, list[str]] = {}
        for version_id, record in self.versions.items():
            parent = record.parent_version_id
            if parent is None:
                continue
            if parent not in self.versions:
                raise ValueError("Every shared parent version must be present")
            children.setdefault(parent, []).append(version_id)
        if any(len(values) > 1 for values in children.values()):
            raise ValueError("Shared plan history cannot branch")
        ordered, current = [], roots[0]
        while True:
            if current in ordered:
                raise ValueError("Shared plan history contains a cycle")
            ordered.append(current)
            descendants = children.get(current, [])
            if not descendants:
                break
            current = descendants[0]
        if len(ordered) != len(self.versions):
            raise ValueError("Shared plan history must be one connected chain")
        if self.current_version_id != ordered[-1]:
            raise ValueError("Shared current version must be the chain leaf")
        return self

    def ordered_versions(self):
        by_parent = {
            record.parent_version_id: version_id
            for version_id, record in self.versions.items()
            if record.parent_version_id is not None
        }
        current = next(
            version_id
            for version_id, record in self.versions.items()
            if record.parent_version_id is None
        )
        ordered = []
        while True:
            ordered.append(self.versions[current])
            if current not in by_parent:
                return ordered
            current = by_parent[current]


class PlanSeedBundle(Contract):
    seed_schema_version: Literal[1] = 1
    plans: dict[str, SeedPlan] = Field(default_factory=dict)

    @model_validator(mode="after")
    def plan_keys_match(self):
        for plan_id, plan in self.plans.items():
            if not plan_id.strip():
                raise ValueError("Seed plan ID cannot be blank")
            if any(record.plan_id != plan_id for record in plan.versions.values()):
                raise ValueError("Seed plan key differs from record plan ID")
        return self


class SeedImportResult(Contract):
    imported: dict[str, list[str]] = Field(default_factory=dict)
    up_to_date: list[str] = Field(default_factory=list)
    local_ahead: dict[str, str] = Field(default_factory=dict)
    dry_run: bool


def load_seed(path: str | Path) -> PlanSeedBundle:
    path = Path(path)
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        return PlanSeedBundle()
    return PlanSeedBundle.model_validate_json(path.read_text(encoding="utf-8"))


def _seed_json(bundle: PlanSeedBundle):
    return (
        json.dumps(
            bundle.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def _write_seed(path: Path, bundle: PlanSeedBundle):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary = Path(output.name)
            output.write(_seed_json(bundle))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _load_lineage(repository: PlanRepository, record: StoredPlanVersion):
    lineage, seen = [], set()
    while True:
        version_id = record.snapshot.version_id
        if version_id in seen:
            raise PlanSeedConflict("Local plan history contains a cycle")
        seen.add(version_id)
        lineage.append(record)
        if record.parent_version_id is None:
            return list(reversed(lineage))
        record = repository.load_version(record.plan_id, record.parent_version_id)


def _same_record(left: StoredPlanVersion, right: StoredPlanVersion):
    return left.model_dump(mode="json") == right.model_dump(mode="json")


def publish_seed(
    repository: PlanRepository,
    seed_path: str | Path,
    plan_id: str,
    version_id: str | None = None,
):
    """Publish one approved version and its ancestry without running Git."""
    target = (
        repository.load_version(plan_id, version_id)
        if version_id is not None
        else repository.load_current(plan_id)
    )
    lineage = _load_lineage(repository, target)
    bundle = load_seed(seed_path)
    raw = bundle.model_dump(mode="json")
    shared = bundle.plans.get(plan_id)
    versions = {} if shared is None else dict(shared.versions)
    added = []
    for record in lineage:
        current_version = record.snapshot.version_id
        existing = versions.get(current_version)
        if existing is not None and not _same_record(existing, record):
            raise PlanSeedConflict(
                f"Shared version has different content: {plan_id}/{current_version}"
            )
        if existing is None:
            versions[current_version] = record
            added.append(current_version)
    if not added:
        return []
    raw["plans"][plan_id] = {
        "current_version_id": target.snapshot.version_id,
        "versions": {
            key: record.model_dump(mode="json") for key, record in versions.items()
        },
    }
    try:
        updated = PlanSeedBundle.model_validate(raw)
    except ValueError as exc:
        raise PlanSeedConflict(
            "Shared plan diverged; pull, import and resimulate from its current version"
        ) from exc
    _write_seed(Path(seed_path), updated)
    return added


def import_seed(
    repository: PlanRepository, seed_path: str | Path, *, dry_run: bool = False
):
    """Import missing linear tails; all affected plans commit atomically."""
    bundle = load_seed(seed_path)
    records_to_save, expected = [], {}
    imported, up_to_date, local_ahead = {}, [], {}
    for plan_id in sorted(bundle.plans):
        shared_lineage = bundle.plans[plan_id].ordered_versions()
        try:
            local_lineage = _load_lineage(repository, repository.load_current(plan_id))
        except KeyError:
            local_lineage = []
        common = min(len(local_lineage), len(shared_lineage))
        for index in range(common):
            if not _same_record(local_lineage[index], shared_lineage[index]):
                raise PlanSeedConflict(
                    f"Local and shared histories diverged: {plan_id}"
                )
        if common < len(local_lineage) and common < len(shared_lineage):
            raise PlanSeedConflict(f"Local and shared histories diverged: {plan_id}")
        if len(local_lineage) > len(shared_lineage):
            local_ahead[plan_id] = local_lineage[-1].snapshot.version_id
            continue
        missing = shared_lineage[len(local_lineage) :]
        if not missing:
            up_to_date.append(plan_id)
            continue
        imported[plan_id] = [record.snapshot.version_id for record in missing]
        expected[plan_id] = (
            local_lineage[-1].snapshot.version_id if local_lineage else None
        )
        records_to_save.extend(missing)
    result = SeedImportResult(
        imported=imported,
        up_to_date=up_to_date,
        local_ahead=local_ahead,
        dry_run=dry_run,
    )
    if records_to_save and not dry_run:
        repository.save_approved_versions(
            records_to_save, expected_current_version_ids=expected
        )
    return result

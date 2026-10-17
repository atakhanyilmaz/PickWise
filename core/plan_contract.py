"""Plan persistence boundary; SQLite storage is implemented separately."""

from typing import Annotated, Literal, Protocol

from pydantic import AwareDatetime, StringConstraints, field_validator, model_validator

from core.domain_rules import Contract, RouteSource
from core.scenarios import PlanSnapshot

Identifier = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1)
]


class StoredPlanVersion(Contract):
    """An explicitly selected, feasible plan and its approval audit metadata.

    Creating this object does not obtain user approval or write to a database.
    """

    schema_version: Literal[1] = 1
    plan_id: Identifier
    parent_version_id: Identifier | None = None
    approved_by: Identifier
    approved_at: AwareDatetime
    snapshot: PlanSnapshot

    @field_validator("snapshot")
    @classmethod
    def recheck_snapshot(cls, snapshot):
        # Nested model instances may have been mutated after validation.
        checked = PlanSnapshot.model_validate(snapshot.model_dump())
        if not checked.version_id.strip():
            raise ValueError("version_id must not be blank")
        if any(
            job.route_source
            not in (RouteSource.USER_APPROVED, RouteSource.DEMO_ASSUMPTION)
            for job in checked.scenario.jobs
        ):
            raise ValueError(
                "Operational plans require approved or explicit demo routes"
            )
        return checked

    @model_validator(mode="after")
    def parent_is_distinct(self):
        if self.parent_version_id == self.snapshot.version_id:
            raise ValueError("A version cannot be its own parent")
        return self


class PlanVersionConflict(ValueError):
    """Current version changed, parent mismatched, or version already exists."""


class PlanRepository(Protocol):
    """Interface only: no database, transaction or approval implementation."""

    def load_current(self, plan_id: str) -> StoredPlanVersion:
        """Return a revalidated record; raise KeyError if the plan is absent."""
        ...

    def load_version(self, plan_id: str, version_id: str) -> StoredPlanVersion:
        """Return a revalidated immutable version; raise KeyError if absent."""
        ...

    def save_approved_version(
        self,
        record: StoredPlanVersion,
        *,
        expected_current_version_id: str | None,
    ) -> None:
        """Atomically insert and advance current; see docs/plan-data-contract.md."""
        ...

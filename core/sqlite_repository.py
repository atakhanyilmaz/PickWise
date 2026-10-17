"""SQLite implementation of PlanRepository; saving requires caller approval."""

import json
import sqlite3
from collections import Counter, defaultdict
from contextlib import contextmanager
from pathlib import Path

from core.plan_contract import PlanVersionConflict, StoredPlanVersion

SCHEMA = Path(__file__).resolve().parents[1] / "database" / "schema.sql"


class PlanStorageError(ValueError):
    """Database structure or relational snapshot is inconsistent."""


def _rows(record):
    """One canonical projection for both writing and checking relational rows."""
    base = {"plan_id": record.plan_id, "version_id": record.snapshot.version_id}
    scenario = record.snapshot.scenario.model_dump(mode="json")
    result = record.snapshot.result.model_dump(mode="json")
    yield (
        "plan_scenarios",
        base
        | {
            k: scenario[k]
            for k in (
                "scenario_id",
                "description",
                "current_time",
                "time_unit",
                "time_unit_note",
            )
        },
    )
    for ordinal, machine in enumerate(scenario["machines"]):
        mb = base | {"machine_id": machine["machine_id"]}
        yield "plan_machines", mb | {"ordinal": ordinal, "name": machine["name"]}
        for i, (start, end) in enumerate(machine["unavailable_intervals"]):
            yield (
                "plan_machine_unavailable_intervals",
                mb | {"ordinal": i, "start_time": start, "end_time": end},
            )
    for ordinal, job in enumerate(scenario["jobs"]):
        jb = base | {"job_id": job["job_id"]}
        yield (
            "plan_jobs",
            jb
            | {"ordinal": ordinal}
            | {
                k: job[k]
                for k in (
                    "name",
                    "route_source",
                    "deadline",
                    "due_date",
                    "release_time",
                )
            },
        )
        for i, op in enumerate(job["operations"]):
            ob = jb | {"operation_id": op["operation_id"]}
            yield (
                "plan_operations",
                ob
                | {"ordinal": i}
                | {
                    k: op[k]
                    for k in (
                        "name",
                        "duration_source",
                        "status",
                        "fixed_machine_id",
                        "fixed_start",
                        "fixed_end",
                        "remaining_duration",
                    )
                },
            )
            for option, (machine, duration) in enumerate(
                op["processing_times"].items()
            ):
                yield (
                    "operation_machine_options",
                    ob
                    | {
                        "machine_id": int(machine),
                        "option_ordinal": option,
                        "duration_minutes": duration,
                    },
                )
    for job_id, limit in scenario["completion_limits"].items():
        yield (
            "plan_job_completion_limits",
            base | {"job_id": int(job_id), "completion_limit": limit},
        )
    yield (
        "schedule_results",
        base
        | {
            k: result[k]
            for k in (
                "status",
                "makespan",
                "best_bound",
                "runtime_seconds",
                "time_limit_seconds",
                "seed",
                "workers",
                "time_unit",
                "objective",
                "scenario_type",
            )
        }
        | {
            k + "_json": json.dumps(result[k])
            for k in ("violations", "source_machine_ids", "source_job_ids")
        },
    )
    for ordinal, row in enumerate(result["schedule"]):
        yield (
            "schedule_rows",
            base
            | {"schedule_ordinal": ordinal}
            | {k + "_index": row[k] for k in ("job", "operation", "machine")}
            | {"start_time": row["start"], "end_time": row["end"]}
            | {
                k: row[k]
                for k in ("source_job_id", "source_operation_id", "source_machine_id")
            },
        )


# Empty optional tables must be checked too, so unexpected rows cannot hide.
TABLES = (
    "plan_scenarios",
    "plan_machines",
    "plan_machine_unavailable_intervals",
    "plan_jobs",
    "plan_operations",
    "operation_machine_options",
    "plan_job_completion_limits",
    "schedule_results",
    "schedule_rows",
)


class SQLitePlanRepository:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    @contextmanager
    def _connection(self):
        # Read/write existing files only: callers must explicitly initialize.
        conn = sqlite3.connect(
            self.path.resolve().as_uri() + "?mode=rw", uri=True, timeout=5
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
        finally:
            if conn.in_transaction:
                conn.rollback()
            conn.close()

    def initialize(self):
        """Create an empty database; leave existing compatible schemas intact.

        No migration of existing databases is performed.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if not tables:
                conn.executescript(
                    "BEGIN IMMEDIATE;\n" + SCHEMA.read_text() + "\nCOMMIT;"
                )
            elif not {"plans", "plan_versions", *TABLES} <= tables:
                raise PlanStorageError("Existing database has an incompatible schema")
        finally:
            if conn.in_transaction:
                conn.rollback()
            conn.close()

    @staticmethod
    def _verify_relational(conn, record):
        expected = defaultdict(list)
        for table, row in _rows(record):
            expected[table].append(row)
        for table in TABLES:
            actual = [
                dict(r)
                for r in conn.execute(
                    f"SELECT * FROM {table} WHERE plan_id=? AND version_id=?",
                    (record.plan_id, record.snapshot.version_id),
                )
            ]

            # Compare values and ordinals, independently of SQLite row order.
            def fingerprint(row):
                return tuple(sorted(row.items()))

            if Counter(map(fingerprint, actual)) != Counter(
                map(fingerprint, expected[table])
            ):
                raise PlanStorageError(
                    f"Relational rows disagree with snapshot: {table}"
                )

    def _load(self, conn, plan_id, version_id):
        row = conn.execute(
            "SELECT * FROM plan_versions WHERE plan_id=? AND version_id=? AND is_complete=1",
            (plan_id, version_id),
        ).fetchone()
        if row is None:
            raise KeyError((plan_id, version_id))
        record = StoredPlanVersion.model_validate(
            {
                "schema_version": row["schema_version"],
                "plan_id": row["plan_id"],
                "parent_version_id": row["parent_version_id"],
                "approved_by": row["approved_by"],
                "approved_at": row["approved_at"],
                "snapshot": json.loads(row["snapshot_json"]),
            }
        )
        if record.snapshot.version_id != row["version_id"]:
            raise PlanStorageError("Snapshot version differs from database version")
        self._verify_relational(conn, record)
        return record

    def load_version(self, plan_id: str, version_id: str) -> StoredPlanVersion:
        with self._connection() as conn:
            conn.execute("BEGIN")
            return self._load(conn, plan_id, version_id)

    def load_current(self, plan_id: str) -> StoredPlanVersion:
        with self._connection() as conn:
            conn.execute("BEGIN")
            row = conn.execute(
                "SELECT current_version_id FROM plans WHERE plan_id=?", (plan_id,)
            ).fetchone()
            if row is None or row[0] is None:
                raise KeyError(plan_id)
            return self._load(conn, plan_id, row[0])

    def save_approved_version(
        self, record: StoredPlanVersion, *, expected_current_version_id: str | None
    ) -> None:
        # Revalidate mutated model instances as well as imported data.
        record = StoredPlanVersion.model_validate_json(record.model_dump_json())
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT current_version_id FROM plans WHERE plan_id=?",
                (record.plan_id,),
            ).fetchone()
            current = row[0] if row is not None else None
            if (
                current != expected_current_version_id
                or record.parent_version_id != current
            ):
                raise PlanVersionConflict(
                    "Plan changed or parent differs; reload before saving"
                )
            if conn.execute(
                "SELECT 1 FROM plan_versions WHERE plan_id=? AND version_id=?",
                (record.plan_id, record.snapshot.version_id),
            ).fetchone():
                raise PlanVersionConflict("Plan version already exists")
            if row is None:
                conn.execute("INSERT INTO plans(plan_id) VALUES (?)", (record.plan_id,))
            conn.execute(
                "INSERT INTO plan_versions(plan_id,version_id,parent_version_id,schema_version,approved_by,approved_at,snapshot_json) VALUES (?,?,?,?,?,?,?)",
                (
                    record.plan_id,
                    record.snapshot.version_id,
                    record.parent_version_id,
                    record.schema_version,
                    record.approved_by,
                    record.approved_at.isoformat(),
                    record.snapshot.model_dump_json(),
                ),
            )
            for table, values in _rows(record):
                columns = ",".join(values)
                placeholders = ",".join("?" for _ in values)
                conn.execute(
                    f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
                    tuple(values.values()),
                )
            self._verify_relational(conn, record)
            conn.execute(
                "UPDATE plan_versions SET is_complete=1 WHERE plan_id=? AND version_id=?",
                (record.plan_id, record.snapshot.version_id),
            )
            updated = conn.execute(
                "UPDATE plans SET current_version_id=? WHERE plan_id=? AND current_version_id IS ?",
                (
                    record.snapshot.version_id,
                    record.plan_id,
                    expected_current_version_id,
                ),
            )
            if updated.rowcount != 1:
                raise PlanVersionConflict("Current version changed")
            conn.commit()

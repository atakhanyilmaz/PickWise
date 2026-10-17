-- SQLite schema for explicitly approved plan versions.
--
-- snapshot_json is the complete, Pydantic-validated PlanSnapshot used for
-- lossless reconstruction. The related tables expose the production and
-- solver data as queryable rows. A writer must populate the full relational
-- snapshot, seal the version, and advance plans.current_version_id in one
-- transaction. Intake messages and temporary simulations are not persisted.
-- Each SQLite connection must enable PRAGMA foreign_keys = ON.

PRAGMA foreign_keys = ON;

CREATE TABLE plans (
    plan_id TEXT PRIMARY KEY CHECK (length(trim(plan_id)) > 0),
    current_version_id TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (plan_id, current_version_id)
        REFERENCES plan_versions (plan_id, version_id)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE plan_versions (
    plan_id TEXT NOT NULL CHECK (length(trim(plan_id)) > 0),
    version_id TEXT NOT NULL CHECK (length(trim(version_id)) > 0),
    parent_version_id TEXT,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    approved_by TEXT NOT NULL CHECK (length(trim(approved_by)) > 0),
    approved_at TEXT NOT NULL CHECK (length(trim(approved_at)) > 0),
    snapshot_json TEXT NOT NULL
        CHECK (json_valid(snapshot_json))
        CHECK (json_type(snapshot_json) = 'object')
        CHECK (json_type(snapshot_json, '$.version_id') IS 'text')
        CHECK (json_extract(snapshot_json, '$.version_id') = version_id),
    is_complete INTEGER NOT NULL DEFAULT 0 CHECK (is_complete IN (0, 1)),
    PRIMARY KEY (plan_id, version_id),
    CHECK (parent_version_id IS NULL OR parent_version_id <> version_id),
    FOREIGN KEY (plan_id) REFERENCES plans (plan_id),
    FOREIGN KEY (plan_id, parent_version_id)
        REFERENCES plan_versions (plan_id, version_id)
        DEFERRABLE INITIALLY DEFERRED
);

-- One workshop scenario is stored for every plan version.
CREATE TABLE plan_scenarios (
    plan_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    current_time INTEGER NOT NULL DEFAULT 0 CHECK (current_time >= 0),
    time_unit TEXT NOT NULL CHECK (time_unit = 'minutes'),
    time_unit_note TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (plan_id, version_id),
    FOREIGN KEY (plan_id, version_id)
        REFERENCES plan_versions (plan_id, version_id)
);

CREATE TABLE plan_machines (
    plan_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    machine_id INTEGER NOT NULL CHECK (machine_id >= 0),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    name TEXT NOT NULL,
    PRIMARY KEY (plan_id, version_id, machine_id),
    UNIQUE (plan_id, version_id, ordinal),
    UNIQUE (plan_id, version_id, ordinal, machine_id),
    FOREIGN KEY (plan_id, version_id)
        REFERENCES plan_scenarios (plan_id, version_id)
);

CREATE TABLE plan_machine_unavailable_intervals (
    plan_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    machine_id INTEGER NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    start_time INTEGER NOT NULL CHECK (start_time >= 0),
    end_time INTEGER NOT NULL CHECK (end_time > start_time),
    PRIMARY KEY (plan_id, version_id, machine_id, ordinal),
    FOREIGN KEY (plan_id, version_id, machine_id)
        REFERENCES plan_machines (plan_id, version_id, machine_id)
);

CREATE TABLE plan_jobs (
    plan_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    job_id INTEGER NOT NULL CHECK (job_id >= 0),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    name TEXT NOT NULL,
    route_source TEXT NOT NULL CHECK (
        route_source IN ('retrospective', 'user_approved', 'user_proposed', 'demo_assumption')
    ),
    deadline INTEGER CHECK (deadline IS NULL OR deadline >= 0),
    due_date INTEGER CHECK (due_date IS NULL OR due_date >= 0),
    release_time INTEGER NOT NULL DEFAULT 0 CHECK (release_time >= 0),
    PRIMARY KEY (plan_id, version_id, job_id),
    UNIQUE (plan_id, version_id, ordinal),
    UNIQUE (plan_id, version_id, ordinal, job_id),
    FOREIGN KEY (plan_id, version_id)
        REFERENCES plan_scenarios (plan_id, version_id)
);

CREATE TABLE plan_job_completion_limits (
    plan_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    job_id INTEGER NOT NULL CHECK (job_id >= 0),
    completion_limit INTEGER NOT NULL CHECK (completion_limit >= 0),
    PRIMARY KEY (plan_id, version_id, job_id),
    FOREIGN KEY (plan_id, version_id, job_id)
        REFERENCES plan_jobs (plan_id, version_id, job_id)
);

CREATE TABLE plan_operations (
    plan_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    job_id INTEGER NOT NULL CHECK (job_id >= 0),
    operation_id INTEGER NOT NULL CHECK (operation_id >= 0),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    name TEXT NOT NULL,
    duration_source TEXT NOT NULL CHECK (
        duration_source IN ('user_input', 'benchmark', 'tabpfn_estimate', 'historical_median', 'demo_assumption')
    ),
    status TEXT NOT NULL CHECK (
        status IN ('not_started', 'in_progress', 'completed')
    ),
    fixed_machine_id INTEGER CHECK (
        fixed_machine_id IS NULL OR fixed_machine_id >= 0
    ),
    fixed_start INTEGER CHECK (fixed_start IS NULL OR fixed_start >= 0),
    fixed_end INTEGER CHECK (fixed_end IS NULL OR fixed_end >= 0),
    remaining_duration INTEGER CHECK (
        remaining_duration IS NULL OR remaining_duration > 0
    ),
    PRIMARY KEY (plan_id, version_id, job_id, operation_id),
    UNIQUE (plan_id, version_id, job_id, ordinal),
    UNIQUE (plan_id, version_id, job_id, ordinal, operation_id),
    FOREIGN KEY (plan_id, version_id, job_id)
        REFERENCES plan_jobs (plan_id, version_id, job_id),
    FOREIGN KEY (
        plan_id, version_id, job_id, operation_id, fixed_machine_id
    ) REFERENCES operation_machine_options (
        plan_id, version_id, job_id, operation_id, machine_id
    ) DEFERRABLE INITIALLY DEFERRED,
    CHECK (
        (status = 'not_started'
            AND fixed_machine_id IS NULL
            AND fixed_start IS NULL
            AND fixed_end IS NULL
            AND remaining_duration IS NULL)
        OR
        (status = 'completed'
            AND fixed_machine_id IS NOT NULL
            AND fixed_start IS NOT NULL
            AND fixed_end IS NOT NULL
            AND fixed_end > fixed_start
            AND remaining_duration IS NULL)
        OR
        (status = 'in_progress'
            AND fixed_machine_id IS NOT NULL
            AND fixed_start IS NOT NULL
            AND fixed_end IS NULL
            AND remaining_duration IS NOT NULL)
    )
);

-- Processing times are machine-specific. option_ordinal preserves dictionary
-- order so loading the snapshot does not silently reorder alternatives.
CREATE TABLE operation_machine_options (
    plan_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    job_id INTEGER NOT NULL CHECK (job_id >= 0),
    operation_id INTEGER NOT NULL CHECK (operation_id >= 0),
    machine_id INTEGER NOT NULL CHECK (machine_id >= 0),
    option_ordinal INTEGER NOT NULL CHECK (option_ordinal >= 0),
    duration_minutes INTEGER NOT NULL CHECK (duration_minutes > 0),
    PRIMARY KEY (plan_id, version_id, job_id, operation_id, machine_id),
    UNIQUE (plan_id, version_id, job_id, operation_id, option_ordinal),
    FOREIGN KEY (plan_id, version_id, job_id, operation_id)
        REFERENCES plan_operations (plan_id, version_id, job_id, operation_id)
        DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (plan_id, version_id, machine_id)
        REFERENCES plan_machines (plan_id, version_id, machine_id)
);

CREATE TABLE schedule_results (
    plan_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('OPTIMAL', 'FEASIBLE', 'INFEASIBLE', 'UNKNOWN', 'MODEL_INVALID')
    ),
    makespan INTEGER CHECK (makespan IS NULL OR makespan >= 0),
    best_bound REAL NOT NULL CHECK (
        best_bound = best_bound AND abs(best_bound) <= 1.7976931348623157e308
    ),
    runtime_seconds REAL NOT NULL CHECK (
        runtime_seconds >= 0 AND runtime_seconds <= 1.7976931348623157e308
    ),
    time_limit_seconds REAL NOT NULL CHECK (
        time_limit_seconds > 0 AND time_limit_seconds <= 1.7976931348623157e308
    ),
    seed INTEGER NOT NULL,
    workers INTEGER NOT NULL,
    violations_json TEXT CHECK (
        violations_json IS NULL OR
        (json_valid(violations_json) AND json_type(violations_json) = 'array')
    ),
    time_unit TEXT NOT NULL CHECK (time_unit = 'minutes'),
    objective TEXT NOT NULL CHECK (
        objective = 'makespan_under_hard_deadlines'
    ),
    scenario_type TEXT NOT NULL CHECK (
        scenario_type IN ('workshop', 'retrospective')
    ),
    source_machine_ids_json TEXT NOT NULL
        CHECK (json_valid(source_machine_ids_json))
        CHECK (json_type(source_machine_ids_json) = 'array'),
    source_job_ids_json TEXT NOT NULL
        CHECK (json_valid(source_job_ids_json))
        CHECK (json_type(source_job_ids_json) = 'array'),
    PRIMARY KEY (plan_id, version_id),
    FOREIGN KEY (plan_id, version_id)
        REFERENCES plan_scenarios (plan_id, version_id),
    CHECK (
        (status IN ('OPTIMAL', 'FEASIBLE')
            AND makespan IS NOT NULL
            AND violations_json IS NOT NULL
            AND json_array_length(violations_json) = 0)
        OR
        (status IN ('INFEASIBLE', 'UNKNOWN', 'MODEL_INVALID')
            AND makespan IS NULL
            AND violations_json IS NULL)
    )
);

CREATE TABLE schedule_rows (
    plan_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    schedule_ordinal INTEGER NOT NULL CHECK (schedule_ordinal >= 0),
    job_index INTEGER NOT NULL CHECK (job_index >= 0),
    operation_index INTEGER NOT NULL CHECK (operation_index >= 0),
    machine_index INTEGER NOT NULL CHECK (machine_index >= 0),
    start_time INTEGER NOT NULL CHECK (start_time >= 0),
    end_time INTEGER NOT NULL CHECK (end_time > start_time),
    source_job_id INTEGER NOT NULL CHECK (source_job_id >= 0),
    source_operation_id INTEGER NOT NULL CHECK (source_operation_id >= 0),
    source_machine_id INTEGER NOT NULL CHECK (source_machine_id >= 0),
    PRIMARY KEY (plan_id, version_id, schedule_ordinal),
    UNIQUE (plan_id, version_id, job_index, operation_index),
    UNIQUE (plan_id, version_id, source_job_id, source_operation_id),
    FOREIGN KEY (plan_id, version_id)
        REFERENCES schedule_results (plan_id, version_id),
    FOREIGN KEY (plan_id, version_id, job_index, source_job_id)
        REFERENCES plan_jobs (plan_id, version_id, ordinal, job_id),
    FOREIGN KEY (
        plan_id, version_id, source_job_id, operation_index, source_operation_id
    ) REFERENCES plan_operations (
        plan_id, version_id, job_id, ordinal, operation_id
    ),
    FOREIGN KEY (plan_id, version_id, machine_index, source_machine_id)
        REFERENCES plan_machines (plan_id, version_id, ordinal, machine_id),
    FOREIGN KEY (
        plan_id, version_id, source_job_id, source_operation_id, source_machine_id
    ) REFERENCES operation_machine_options (
        plan_id, version_id, job_id, operation_id, machine_id
    )
);

CREATE INDEX plan_jobs_due_date_idx
    ON plan_jobs (plan_id, version_id, due_date);
CREATE INDEX plan_operations_status_idx
    ON plan_operations (plan_id, version_id, status);
CREATE INDEX schedule_rows_machine_time_idx
    ON schedule_rows (plan_id, version_id, source_machine_id, start_time);

-- Only one linear version history is allowed per plan family.
CREATE UNIQUE INDEX plan_versions_one_root_idx
    ON plan_versions (plan_id)
    WHERE parent_version_id IS NULL;
CREATE UNIQUE INDEX plan_versions_one_child_idx
    ON plan_versions (plan_id, parent_version_id)
    WHERE parent_version_id IS NOT NULL;

CREATE TRIGGER plans_start_without_current_version
BEFORE INSERT ON plans
WHEN NEW.current_version_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'new plan must start without a current version');
END;

CREATE TRIGGER plans_metadata_is_immutable
BEFORE UPDATE ON plans
WHEN NEW.plan_id IS NOT OLD.plan_id
  OR NEW.created_at IS NOT OLD.created_at
BEGIN
    SELECT RAISE(ABORT, 'plan identity metadata is immutable');
END;

CREATE TRIGGER plan_versions_must_start_open
BEFORE INSERT ON plan_versions
WHEN NEW.is_complete <> 0
BEGIN
    SELECT RAISE(ABORT, 'plan version must be created incomplete');
END;

CREATE TRIGGER plan_versions_follow_current
BEFORE INSERT ON plan_versions
WHEN NOT EXISTS (
    SELECT 1
    FROM plans
    WHERE plan_id = NEW.plan_id
      AND current_version_id IS NEW.parent_version_id
)
BEGIN
    SELECT RAISE(ABORT, 'version parent must match current plan version');
END;

CREATE TRIGGER plan_versions_cannot_be_reinserted
BEFORE INSERT ON plan_versions
WHEN EXISTS (
    SELECT 1 FROM plan_versions
    WHERE plan_id = NEW.plan_id AND version_id = NEW.version_id
)
BEGIN
    SELECT RAISE(ABORT, 'plan version already exists');
END;

-- Sealing is the sole permitted update to a version header. A sealed version
-- cannot subsequently be edited or deleted.
CREATE TRIGGER plan_versions_seal_once
BEFORE UPDATE ON plan_versions
WHEN OLD.is_complete <> 0
  OR NEW.is_complete <> 1
  OR NEW.plan_id IS NOT OLD.plan_id
  OR NEW.version_id IS NOT OLD.version_id
  OR NEW.parent_version_id IS NOT OLD.parent_version_id
  OR NEW.schema_version IS NOT OLD.schema_version
  OR NEW.approved_by IS NOT OLD.approved_by
  OR NEW.approved_at IS NOT OLD.approved_at
  OR NEW.snapshot_json IS NOT OLD.snapshot_json
BEGIN
    SELECT RAISE(ABORT, 'only an incomplete version may be sealed once');
END;

CREATE TRIGGER plan_versions_validate_before_seal
BEFORE UPDATE OF is_complete ON plan_versions
WHEN OLD.is_complete = 0 AND NEW.is_complete = 1
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM plan_scenarios
        WHERE plan_id = NEW.plan_id AND version_id = NEW.version_id
    ) THEN RAISE(ABORT, 'scenario is required before sealing') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM plan_machines
        WHERE plan_id = NEW.plan_id AND version_id = NEW.version_id
    ) THEN RAISE(ABORT, 'machines are required before sealing') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM plan_jobs
        WHERE plan_id = NEW.plan_id AND version_id = NEW.version_id
    ) THEN RAISE(ABORT, 'jobs are required before sealing') END;
    SELECT CASE WHEN EXISTS (
        SELECT 1 FROM plan_jobs AS j
        WHERE j.plan_id = NEW.plan_id AND j.version_id = NEW.version_id
          AND NOT EXISTS (
              SELECT 1 FROM plan_operations AS o
              WHERE o.plan_id = j.plan_id AND o.version_id = j.version_id
                AND o.job_id = j.job_id
          )
    ) THEN RAISE(ABORT, 'every job must contain an operation') END;
    SELECT CASE WHEN EXISTS (
        SELECT 1 FROM plan_jobs
        WHERE plan_id = NEW.plan_id AND version_id = NEW.version_id
          AND route_source NOT IN ('user_approved', 'demo_assumption')
    ) THEN RAISE(ABORT, 'approved plans require approved or demo routes') END;
    SELECT CASE WHEN EXISTS (
        SELECT 1 FROM plan_operations AS o
        WHERE o.plan_id = NEW.plan_id AND o.version_id = NEW.version_id
          AND NOT EXISTS (
              SELECT 1 FROM operation_machine_options AS x
              WHERE x.plan_id = o.plan_id AND x.version_id = o.version_id
                AND x.job_id = o.job_id AND x.operation_id = o.operation_id
          )
    ) THEN RAISE(ABORT, 'every operation needs an eligible machine option') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM schedule_results
        WHERE plan_id = NEW.plan_id AND version_id = NEW.version_id
          AND status IN ('OPTIMAL', 'FEASIBLE')
          AND makespan IS NOT NULL
          AND json_array_length(violations_json) = 0
    ) THEN RAISE(ABORT, 'approved plan requires a feasible solver result') END;
    SELECT CASE WHEN (
        SELECT COUNT(*) FROM plan_operations
        WHERE plan_id = NEW.plan_id AND version_id = NEW.version_id
    ) <> (
        SELECT COUNT(*) FROM schedule_rows
        WHERE plan_id = NEW.plan_id AND version_id = NEW.version_id
    ) THEN RAISE(ABORT, 'schedule must contain every operation exactly once') END;
    SELECT CASE WHEN (
        SELECT makespan FROM schedule_results
        WHERE plan_id = NEW.plan_id AND version_id = NEW.version_id
    ) <> (
        SELECT MAX(end_time) FROM schedule_rows
        WHERE plan_id = NEW.plan_id AND version_id = NEW.version_id
    ) THEN RAISE(ABORT, 'makespan must match the schedule') END;
END;

CREATE TRIGGER plans_advance_to_complete_child
BEFORE UPDATE OF current_version_id ON plans
WHEN NEW.current_version_id IS NOT OLD.current_version_id
 AND NOT EXISTS (
    SELECT 1 FROM plan_versions
    WHERE plan_id = NEW.plan_id
      AND version_id = NEW.current_version_id
      AND parent_version_id IS OLD.current_version_id
      AND is_complete = 1
 )
BEGIN
    SELECT RAISE(ABORT, 'current version must advance to a sealed direct child');
END;

CREATE TRIGGER plan_versions_are_immutable_delete
BEFORE DELETE ON plan_versions
BEGIN
    SELECT RAISE(ABORT, 'plan versions cannot be deleted');
END;

CREATE TRIGGER plan_machine_intervals_do_not_overlap
BEFORE INSERT ON plan_machine_unavailable_intervals
WHEN EXISTS (
    SELECT 1 FROM plan_machine_unavailable_intervals AS old
    WHERE old.plan_id = NEW.plan_id AND old.version_id = NEW.version_id
      AND old.machine_id = NEW.machine_id
      AND NEW.start_time < old.end_time AND old.start_time < NEW.end_time
)
BEGIN
    SELECT RAISE(ABORT, 'machine unavailable intervals cannot overlap');
END;

-- Child rows can be written only while their plan version is being assembled.
CREATE TRIGGER plan_scenarios_open_insert
BEFORE INSERT ON plan_scenarios
WHEN NOT EXISTS (
    SELECT 1 FROM plan_versions
    WHERE plan_id = NEW.plan_id AND version_id = NEW.version_id
      AND is_complete = 0
)
BEGIN
    SELECT RAISE(ABORT, 'plan version is sealed or missing');
END;

CREATE TRIGGER plan_machines_open_insert
BEFORE INSERT ON plan_machines
WHEN NOT EXISTS (
    SELECT 1 FROM plan_versions
    WHERE plan_id = NEW.plan_id AND version_id = NEW.version_id
      AND is_complete = 0
)
BEGIN
    SELECT RAISE(ABORT, 'plan version is sealed or missing');
END;

CREATE TRIGGER plan_machine_intervals_open_insert
BEFORE INSERT ON plan_machine_unavailable_intervals
WHEN NOT EXISTS (
    SELECT 1 FROM plan_versions
    WHERE plan_id = NEW.plan_id AND version_id = NEW.version_id
      AND is_complete = 0
)
BEGIN
    SELECT RAISE(ABORT, 'plan version is sealed or missing');
END;

CREATE TRIGGER plan_jobs_open_insert
BEFORE INSERT ON plan_jobs
WHEN NOT EXISTS (
    SELECT 1 FROM plan_versions
    WHERE plan_id = NEW.plan_id AND version_id = NEW.version_id
      AND is_complete = 0
)
BEGIN
    SELECT RAISE(ABORT, 'plan version is sealed or missing');
END;

CREATE TRIGGER plan_job_limits_open_insert
BEFORE INSERT ON plan_job_completion_limits
WHEN NOT EXISTS (
    SELECT 1 FROM plan_versions
    WHERE plan_id = NEW.plan_id AND version_id = NEW.version_id
      AND is_complete = 0
)
BEGIN
    SELECT RAISE(ABORT, 'plan version is sealed or missing');
END;

CREATE TRIGGER plan_operations_open_insert
BEFORE INSERT ON plan_operations
WHEN NOT EXISTS (
    SELECT 1 FROM plan_versions
    WHERE plan_id = NEW.plan_id AND version_id = NEW.version_id
      AND is_complete = 0
)
BEGIN
    SELECT RAISE(ABORT, 'plan version is sealed or missing');
END;

CREATE TRIGGER operation_options_open_insert
BEFORE INSERT ON operation_machine_options
WHEN NOT EXISTS (
    SELECT 1 FROM plan_versions
    WHERE plan_id = NEW.plan_id AND version_id = NEW.version_id
      AND is_complete = 0
)
BEGIN
    SELECT RAISE(ABORT, 'plan version is sealed or missing');
END;

CREATE TRIGGER schedule_results_open_insert
BEFORE INSERT ON schedule_results
WHEN NOT EXISTS (
    SELECT 1 FROM plan_versions
    WHERE plan_id = NEW.plan_id AND version_id = NEW.version_id
      AND is_complete = 0
)
BEGIN
    SELECT RAISE(ABORT, 'plan version is sealed or missing');
END;

CREATE TRIGGER schedule_rows_open_insert
BEFORE INSERT ON schedule_rows
WHEN NOT EXISTS (
    SELECT 1 FROM plan_versions
    WHERE plan_id = NEW.plan_id AND version_id = NEW.version_id
      AND is_complete = 0
)
BEGIN
    SELECT RAISE(ABORT, 'plan version is sealed or missing');
END;

-- Once a version is sealed, every relational snapshot row is immutable.
CREATE TRIGGER plan_scenarios_immutable_update
BEFORE UPDATE ON plan_scenarios
BEGIN SELECT RAISE(ABORT, 'plan snapshot is immutable'); END;
CREATE TRIGGER plan_scenarios_immutable_delete
BEFORE DELETE ON plan_scenarios
BEGIN SELECT RAISE(ABORT, 'plan snapshot is immutable'); END;
CREATE TRIGGER plan_machines_immutable_update
BEFORE UPDATE ON plan_machines
BEGIN SELECT RAISE(ABORT, 'plan snapshot is immutable'); END;
CREATE TRIGGER plan_machines_immutable_delete
BEFORE DELETE ON plan_machines
BEGIN SELECT RAISE(ABORT, 'plan snapshot is immutable'); END;
CREATE TRIGGER plan_machine_intervals_immutable_update
BEFORE UPDATE ON plan_machine_unavailable_intervals
BEGIN SELECT RAISE(ABORT, 'plan snapshot is immutable'); END;
CREATE TRIGGER plan_machine_intervals_immutable_delete
BEFORE DELETE ON plan_machine_unavailable_intervals
BEGIN SELECT RAISE(ABORT, 'plan snapshot is immutable'); END;
CREATE TRIGGER plan_jobs_immutable_update
BEFORE UPDATE ON plan_jobs
BEGIN SELECT RAISE(ABORT, 'plan snapshot is immutable'); END;
CREATE TRIGGER plan_jobs_immutable_delete
BEFORE DELETE ON plan_jobs
BEGIN SELECT RAISE(ABORT, 'plan snapshot is immutable'); END;
CREATE TRIGGER plan_job_limits_immutable_update
BEFORE UPDATE ON plan_job_completion_limits
BEGIN SELECT RAISE(ABORT, 'plan snapshot is immutable'); END;
CREATE TRIGGER plan_job_limits_immutable_delete
BEFORE DELETE ON plan_job_completion_limits
BEGIN SELECT RAISE(ABORT, 'plan snapshot is immutable'); END;
CREATE TRIGGER plan_operations_immutable_update
BEFORE UPDATE ON plan_operations
BEGIN SELECT RAISE(ABORT, 'plan snapshot is immutable'); END;
CREATE TRIGGER plan_operations_immutable_delete
BEFORE DELETE ON plan_operations
BEGIN SELECT RAISE(ABORT, 'plan snapshot is immutable'); END;
CREATE TRIGGER operation_options_immutable_update
BEFORE UPDATE ON operation_machine_options
BEGIN SELECT RAISE(ABORT, 'plan snapshot is immutable'); END;
CREATE TRIGGER operation_options_immutable_delete
BEFORE DELETE ON operation_machine_options
BEGIN SELECT RAISE(ABORT, 'plan snapshot is immutable'); END;
CREATE TRIGGER schedule_results_immutable_update
BEFORE UPDATE ON schedule_results
BEGIN SELECT RAISE(ABORT, 'plan snapshot is immutable'); END;
CREATE TRIGGER schedule_results_immutable_delete
BEFORE DELETE ON schedule_results
BEGIN SELECT RAISE(ABORT, 'plan snapshot is immutable'); END;
CREATE TRIGGER schedule_rows_immutable_update
BEFORE UPDATE ON schedule_rows
BEGIN SELECT RAISE(ABORT, 'plan snapshot is immutable'); END;
CREATE TRIGGER schedule_rows_immutable_delete
BEFORE DELETE ON schedule_rows
BEGIN SELECT RAISE(ABORT, 'plan snapshot is immutable'); END;

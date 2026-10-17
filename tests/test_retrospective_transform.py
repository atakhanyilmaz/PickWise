"""Production Analysis → initial workshop plan, and the UI running on that plan."""

import pandas as pd
import pytest

from core import retrospective_transform as production
from core.domain_rules import DurationSource, RouteSource
from core.sqlite_repository import SQLitePlanRepository
from core.validation import validate_workshop


@pytest.fixture(scope="module")
def records():
    return production.load_records()


@pytest.fixture(scope="module")
def scenario(records):
    return production.build_scenario(records)


@pytest.fixture(scope="module")
def initial():
    return production.initial_record("Nazlısu Başak")


def test_overlapping_reports_count_once():
    rows = pd.DataFrame(
        {
            "start": pd.to_datetime(
                ["2012-01-01 00:00", "2012-01-01 00:00", "2012-01-01 02:00"]
            ),
            "end": pd.to_datetime(
                ["2012-01-01 01:15", "2012-01-01 01:15", "2012-01-01 02:30"]
            ),
        }
    )
    assert production.busy_minutes(rows) == 105


def test_only_machine_resources_become_machines(records, scenario):
    assert records["Resource"].str.contains("Machine").all()
    assert not records["Resource"].str.startswith("Manual").any()
    assert all(m.name.startswith(f"M{m.machine_id} ") for m in scenario.machines)


def test_routes_are_labelled_as_assumptions_with_median_durations(scenario):
    assert len(scenario.jobs) == production.PLAN_JOBS
    assert {j.route_source for j in scenario.jobs} == {RouteSource.DEMO_ASSUMPTION}
    operations = [op for job in scenario.jobs for op in job.operations]
    assert {op.duration_source for op in operations} == {
        DurationSource.HISTORICAL_MEDIAN
    }
    # The recorded machine only: no alternative machines are inferred.
    assert all(len(op.processing_times) == 1 for op in operations)
    assert len(scenario.jobs_for_solver()) == len(scenario.jobs)


def test_initial_plan_is_solved_and_independently_valid(initial):
    snapshot = initial.snapshot
    assert snapshot.version_id == "v1" and initial.parent_version_id is None
    assert snapshot.result.status in ("OPTIMAL", "FEASIBLE")
    rows = [row.model_dump() for row in snapshot.result.schedule]
    assert validate_workshop(snapshot.scenario, rows) == []


def test_drafts_fit_the_plan_and_are_new_orders(records, scenario):
    drafts = production.order_drafts(scenario, records)
    machines = {m.machine_id for m in scenario.machines}
    assert len(drafts) == production.DRAFT_JOBS
    assert not {d.job_id for d in drafts} & {j.job_id for j in scenario.jobs}
    assert all(
        set(op.processing_times) <= machines for d in drafts for op in d.operations
    )


@pytest.fixture
def saved_plan(tmp_path, monkeypatch, initial):
    """The initial plan stored in a temporary database that the UI reads."""
    from ui import pages

    path = tmp_path / "workshop.sqlite3"
    repository = SQLitePlanRepository(path)
    repository.initialize()
    repository.save_approved_version(initial, expected_current_version_id=None)
    monkeypatch.setattr(pages, "DB", path)
    return path


def test_ui_reads_the_stored_plan(saved_plan):
    from ui import pages

    snapshot, label, saved = pages.current_plan()
    assert saved and snapshot.version_id == "v1" and "v1" in label
    assert snapshot.scenario.scenario_id == production.SCENARIO_ID
    drafts = pages.order_drafts(snapshot)
    assert next(iter(drafts)).startswith("İş emri")


def test_simulation_page_orders_and_saves_on_the_stored_plan(saved_plan):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string(
        "from ui import components as ui, pages\n"
        "_, label, saved = pages.current_plan()\n"
        "ui.sidebar_settings(label, saved)\n"
        "pages.simulation_page()\n",
        default_timeout=120,
    ).run()
    app.button(key="FormSubmitter:change-Simüle et").click().run()
    assert not app.exception and app.success
    app.text_input[0].input("Nazlısu Başak").run()
    next(c for c in app.checkbox if "kaydetmeyi onaylıyorum" in c.label).check().run()
    next(b for b in app.button if b.label == "Planı kaydet").click().run()
    record = SQLitePlanRepository(saved_plan).load_current(production.PLAN_ID)
    assert record.parent_version_id == "v1"

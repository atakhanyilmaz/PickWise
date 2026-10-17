"""Simulation page: order and downtime changes, infeasible outcomes and saving a new plan version."""

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from core.plan_contract import PlanVersionConflict  # noqa: E402
from core.sqlite_repository import SQLitePlanRepository  # noqa: E402
from ui import pages  # noqa: E402

SETUP = """
from ui import components as ui, pages
ui.brand()
_, label, saved = pages.current_plan()
ui.sidebar_settings(label, saved)
pages.{page}()
"""


@pytest.fixture(autouse=True)
def temporary_database(tmp_path, monkeypatch):
    """Never touch the real local database; every test starts without a saved plan."""
    monkeypatch.setattr(pages, "DB", tmp_path / "workshop.sqlite3")
    return pages.DB


def open_page(page="simulation_page"):
    return AppTest.from_string(SETUP.format(page=page), default_timeout=120).run()


def simulate(app):
    app.button(key="FormSubmitter:change-Simüle et").click().run()
    assert not app.exception
    return app


def test_demo_order_shows_before_after_and_impacts():
    app = simulate(open_page())
    assert app.success[0].value.startswith("Bu model ve hedef için optimum")
    assert app.metric[0].value == "08:25" and app.metric[0].delta == "+10 dk"
    impacts = app.dataframe[0].value
    assert impacts.loc[impacts["İş"] == "Bekleyen mevcut iş", "Fark (dk)"].item() == 10


def test_downtime_on_a_started_operation_is_explained_in_turkish():
    app = open_page()
    app.segmented_control[0].set_value("Makine duruşu").run()
    simulate(app)  # default: Torna 1 from now, where an operation is in progress
    assert "başlamış bir işlemle çakışıyor" in app.error[0].value


def test_downtime_on_a_free_machine_is_feasible():
    app = open_page()
    app.segmented_control[0].set_value("Makine duruşu").run()
    app.selectbox[0].select_index(1)  # Torna 2
    simulate(app)
    assert app.success and not app.error


def test_infeasible_change_offers_no_save():
    app = open_page()
    # The demo order keeps its hard deadline (t=20); together with protected finishes
    # there is no room for it on Torna 1.
    assert next(c for c in app.checkbox if c.label == "Sert termin").value
    next(c for c in app.checkbox if "bitiş saatlerini koru" in c.label).check()
    simulate(app)
    assert "uygulanabilir plan yok" in app.error[0].value
    assert not [b for b in app.button if b.label == "Planı kaydet"]


def test_saving_creates_the_active_plan(temporary_database):
    app = simulate(open_page())
    save = next(b for b in app.button if b.label == "Planı kaydet")
    assert save.disabled
    app.text_input[0].input("Nazlısu Başak").run()
    next(c for c in app.checkbox if "kaydetmeyi onaylıyorum" in c.label).check().run()
    next(b for b in app.button if b.label == "Planı kaydet").click().run()
    assert not app.exception
    assert "etkin plan oldu" in app.success[0].value

    record = SQLitePlanRepository(temporary_database).load_current(pages.PLAN_ID)
    assert record.approved_by == "Nazlısu Başak" and record.parent_version_id is None
    plan = open_page("plan_page")
    assert record.snapshot.version_id in plan.caption[0].value


def test_save_is_rejected_when_the_plan_moved(temporary_database):
    baseline, _, _ = pages.current_plan()
    pages.save_plan(baseline, None, "A")
    with pytest.raises(PlanVersionConflict):
        pages.save_plan(baseline, None, "B")  # still claims there is no saved plan

"""Review regressions for edited durations and a plan completed before current time."""

from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402
from benchmarks.workshop_order_demo import DemoInput  # noqa: E402
from core.scenarios import create_snapshot  # noqa: E402
from ui import components, pages  # noqa: E402


@pytest.mark.parametrize("duration", [1.5, 0, -1, float("inf")])
def test_route_editor_rejects_invalid_duration_without_truncation(duration):
    demo = DemoInput.model_validate_json(
        Path("data/examples/order_demo.json").read_text()
    )
    frame = pd.DataFrame(
        [{"Operasyon": "Tornalama", "Torna 1": duration, "Torna 2": None}]
    )
    job, errors = components.job_from_route(
        frame, name="Yeni iş", base=None, machines=demo.baseline.machines, job_id=30
    )
    assert job is None
    assert any("pozitif tam sayı" in message for message in errors)


def test_completed_plan_renders_when_current_time_exceeds_makespan(monkeypatch):
    demo = DemoInput.model_validate_json(
        Path("data/examples/order_demo.json").read_text()
    )
    scenario = demo.baseline.model_copy(deep=True)
    scenario.jobs = scenario.jobs[:1]
    scenario.jobs[0].operations = scenario.jobs[0].operations[:1]
    scenario.current_time = 10
    snapshot = create_snapshot(scenario, "completed", 2)
    assert snapshot.result.makespan == 3
    monkeypatch.setattr(
        pages, "current_plan", lambda: (snapshot, "Tamamlanmış demo", False)
    )
    app = AppTest.from_string(
        "from ui import components as ui, pages\nui.sidebar_settings('demo', False)\npages.plan_page()",
        default_timeout=30,
    ).run()
    assert not app.exception

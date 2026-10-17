"""Headless smoke tests: every Streamlit page renders, and route approval needs an explicit action."""

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

SETUP = """
from ui import components as ui, pages
ui.brand()
_, label, saved = pages.current_plan()
ui.sidebar_settings(label, saved)
"""


def render(page):
    return AppTest.from_string(SETUP + f"pages.{page}()", default_timeout=120).run()


@pytest.mark.parametrize(
    "page",
    ["plan_page", "route_page", "benchmark_page", "experiment_page", "about_page"],
)
def test_page_renders(page):
    assert not render(page).exception


def test_route_is_approved_only_after_checkbox_and_button():
    app = render("route_page")
    assert app.button[0].disabled
    app.checkbox[0].check().run()
    app.button[0].click().run()
    assert not app.exception
    assert app.session_state["approved_order"].route_source == "user_approved"


def test_empty_route_explains_what_is_missing():
    app = render("route_page")
    app.segmented_control[0].set_value("Boş rota").run()
    assert [w.value for w in app.warning] == [
        "Sipariş adı yazın.",
        "En az bir operasyon ekleyin.",
    ]

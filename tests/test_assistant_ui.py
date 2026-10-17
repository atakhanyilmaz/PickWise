"""Gemma assistant page with a scripted model: questions, approval, explanation and saving.

Real Gemma quality is evaluated separately (benchmarks/gemma_*); these tests check the page wiring.
"""

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from core.llm.conversation import IntentDecision, OrderFields  # noqa: E402
from core.llm.ollama_client import ModelUnavailable  # noqa: E402
from core.sqlite_repository import SQLitePlanRepository  # noqa: E402
from ui import assistant, pages  # noqa: E402

SETUP = """
from ui import assistant, components as ui, pages
ui.brand()
_, label, saved = pages.current_plan()
ui.sidebar_settings(label, saved)
assistant.assistant_page()
"""
ORDER = "Yeni sipariş: Torna 1 üzerinde 10 dakika tornalama."
METADATA = {
    "model_tag": "gemma-test",
    "parameter_size": "test",
    "quantization": "test",
    "ollama_version": "test",
    "endpoint": "http://127.0.0.1:11434",
}


class ScriptedClient:
    """Fixed intent and fields; anything else is refused so explanations use computed text."""

    def __init__(self, duration="10 dakika"):
        self.duration = duration

    def structured(self, schema, system, data, prompt_version):
        meta = {"model_tag": "gemma-test", "prompt_version": prompt_version}
        if schema is IntentDecision:
            return IntentDecision(tool="simulate_order", evidence="Yeni sipariş"), meta
        if schema is OrderFields:
            option = {"machine_text": "Torna 1", "duration_text": self.duration}
            return OrderFields(
                order_name=None,
                operations=[{"name": "Tornalama", "options": [option]}],
                deadline_kind="none",
                deadline_text=None,
                preservation="none",
                preservation_text=None,
            ), meta
        raise ModelUnavailable("not scripted")


@pytest.fixture(autouse=True)
def offline(tmp_path, monkeypatch):
    """No Ollama and no real database: a scripted model and a temporary SQLite file."""
    monkeypatch.setattr(pages, "DB", tmp_path / "workshop.sqlite3")
    monkeypatch.setattr(assistant, "installed_models", lambda: [])
    monkeypatch.setattr(
        assistant, "connect", lambda model: (ScriptedClient(), METADATA, None)
    )
    return pages.DB


def open_page():
    return AppTest.from_string(SETUP, default_timeout=120).run()


def ask(app, text):
    app.chat_input[0].set_value(text).run()
    assert not app.exception
    return app


def button(app, label):
    return next(b for b in app.button if b.label == label)


def test_without_gemma_the_page_points_to_manual_entry(monkeypatch):
    monkeypatch.setattr(
        assistant, "connect", lambda model: (None, None, "Ollama çalışmıyor.")
    )
    app = open_page()
    assert not app.exception and not app.chat_input
    assert "Simülasyon" in app.info[0].value


def test_complete_order_waits_for_approval_then_explains_computed_facts():
    app = ask(open_page(), ORDER)
    assert "Kontrol edip onaylarsanız" in app.chat_message[-1].markdown[0].value
    proposal = app.dataframe[0].value
    assert proposal["Makine ve süre"].item() == "Torna 1 10 dk"
    assert app.chat_input[0].disabled  # only the buttons can approve
    assert not [b for b in app.button if b.label == "Planı kaydet"]

    button(app, "Onayla ve simüle et").click().run()
    assert not app.exception
    assert any("başlangıç planı değiştirilmedi" in m.value for m in app.markdown)
    assert any("Hesaplanan metin" in m.value for m in app.markdown)
    assert button(app, "Planı kaydet").disabled


def test_missing_duration_is_asked_in_the_chat(monkeypatch):
    client = ScriptedClient(duration=None)
    monkeypatch.setattr(assistant, "connect", lambda model: (client, METADATA, None))
    app = ask(open_page(), "Yeni sipariş: Torna 1 üzerinde tornalama.")
    assert "süre" in app.chat_message[-1].markdown[0].value.lower()
    app = ask(app, "iki saat")
    assert app.dataframe[0].value["Makine ve süre"].item() == "Torna 1 120 dk"


def test_declined_order_is_not_simulated():
    app = ask(open_page(), ORDER)
    button(app, "Vazgeç").click().run()
    assert "Onay verilmedi" in app.chat_message[-1].markdown[0].value
    assert not [b for b in app.button if b.label == "Planı kaydet"]
    button(app, "Yeni talep").click().run()
    assert not app.chat_message


def test_saving_from_the_assistant_creates_a_plan_version(offline):
    app = ask(open_page(), ORDER)
    button(app, "Onayla ve simüle et").click().run()
    app.text_input[0].input("Nazlısu Başak").run()
    next(c for c in app.checkbox if "kaydetmeyi onaylıyorum" in c.label).check().run()
    button(app, "Planı kaydet").click().run()
    assert not app.exception
    assert "etkin plan oldu" in app.success[0].value
    assert not app.chat_message  # the conversation starts over on the new plan
    record = SQLitePlanRepository(offline).load_current(pages.PLAN_ID)
    assert record.approved_by == "Nazlısu Başak"

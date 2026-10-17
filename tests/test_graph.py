"""LangGraph order flow with scripted model answers; real Gemma is evaluated separately."""

from pathlib import Path

import pytest
from langgraph.types import Command

from benchmarks.workshop_order_demo import DemoInput
from core.llm.conversation import IntentDecision, OrderFields
from core.llm.graph import build_order_graph
from core.llm.ollama_client import ModelUnavailable
from core.scenarios import create_snapshot


class ScriptedClient:
    """Returns fixed intent and fields; refuses anything else so explanations use the fallback."""

    def __init__(self, duration="10 dakika", tool="simulate_order"):
        self.duration, self.tool = duration, tool

    def structured(self, schema, system, data, prompt_version):
        meta = {"test_double": True, "prompt_version": prompt_version}
        if schema is IntentDecision:
            return IntentDecision(tool=self.tool, evidence="Yeni sipariş"), meta
        if schema is OrderFields:
            return OrderFields(
                order_name=None,
                operations=[
                    {
                        "name": "Tornalama",
                        "options": [
                            {"machine_text": "Torna 1", "duration_text": self.duration}
                        ],
                    }
                ],
                deadline_kind="none",
                deadline_text=None,
                preservation="none",
                preservation_text=None,
            ), meta
        raise ModelUnavailable("not scripted")


@pytest.fixture(scope="module")
def baseline():
    demo = DemoInput.model_validate_json(
        Path("data/examples/order_demo.json").read_text()
    )
    return create_snapshot(demo.baseline, "v1", 5)


# The intake only accepts a duration that appears in the user's own words.
FULL_ORDER = "Yeni sipariş: Torna 1 üzerinde 10 dakika tornalama."


def start(baseline, client, text=FULL_ORDER):
    graph = build_order_graph(baseline, client, time_limit=5)
    config = {"configurable": {"thread_id": "test"}}
    return graph, config, graph.invoke({"text": text}, config)


def pause(output):
    return output["__interrupt__"][0].value


def test_missing_duration_is_asked_then_order_waits_for_approval(baseline):
    graph, config, out = start(
        baseline,
        ScriptedClient(duration=None),
        text="Yeni sipariş: Torna 1 üzerinde tornalama.",
    )
    assert pause(out)["kind"] == "question"
    out = graph.invoke(Command(resume="iki saat"), config)
    proposal = pause(out)
    assert proposal["kind"] == "confirmation"
    assert proposal["order"]["operations"][0]["processing_times"] == {100: 120}
    assert "simulation" not in out


def test_approval_runs_simulation_dispatch_and_explanation(baseline):
    before = baseline.model_dump()
    graph, config, out = start(baseline, ScriptedClient())
    out = graph.invoke(Command(resume=True), config)
    assert out["simulation"]["comparison"] is not None
    assert {s["machine_name"] for s in out["dispatch"]} == {"Torna 1", "Torna 2"}
    assert "başlangıç planı değiştirilmedi" in out["explanation"]
    assert baseline.model_dump() == before


def test_declined_proposal_never_simulates(baseline):
    graph, config, out = start(baseline, ScriptedClient())
    out = graph.invoke(Command(resume=False), config)
    assert "simulation" not in out
    assert out["message"] == "Onay verilmedi; simülasyon çalıştırılmadı."


def test_unsupported_request_stops_without_pausing(baseline):
    _, _, out = start(baseline, ScriptedClient(), text="Torna 1 için duruş ekle.")
    assert "__interrupt__" not in out
    assert "desteklenmiyor" in out["message"]

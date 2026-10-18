"""LangGraph order flow with scripted model answers; real Gemma is evaluated separately."""

from pathlib import Path

import pytest
from langgraph.types import Command

from benchmarks.workshop_order_demo import DemoInput
from core.domain_rules import JobModel
from core.llm.conversation import IntentDecision, OrderFields
from core.llm.graph import build_order_graph
from core.llm.ollama_client import InvalidModelOutput, ModelUnavailable
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
    order = JobModel.model_validate(proposal["order"])
    assert order.operations[0].processing_times == {100: 120}
    assert "simulation" not in out


def test_approval_runs_simulation_dispatch_and_explanation(baseline):
    before = baseline.model_dump()
    graph, config, out = start(baseline, ScriptedClient())
    out = graph.invoke(Command(resume=True), config)
    assert out["simulation"]["comparison"] is not None
    assert {s["machine_name"] for s in out["dispatch"]} == {"Torna 1", "Torna 2"}
    assert "başlangıç planı değiştirilmedi" in out["explanation"]["text"]
    assert out["explanation"]["origin"] == "computed_fallback"
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


def test_inspection_request_is_answered_from_computed_plan_facts(baseline):
    _, _, out = start(
        baseline,
        ScriptedClient(tool="inspect_plan"),
        text="Yeni sipariş almadan önce kaç iş bekliyor?",
    )
    assert "__interrupt__" not in out and "simulation" not in out
    assert out["inspection"]["workload"]["total_job_count"] == 2
    assert out["message"].startswith("Yüklü planda")
    assert "Plan değiştirilmedi" in out["message"]


def test_case_insensitive_and_suffixed_evidence_reaches_confirmation(baseline):
    _, _, out = start(
        baseline,
        ScriptedClient(),
        text="Yeni sipariş: torna 1de 10 dakikada tornalama.",
    )
    proposal = pause(out)
    assert proposal["kind"] == "confirmation"
    order = JobModel.model_validate(proposal["order"])
    assert order.operations[0].processing_times == {100: 10}


def test_empty_evidence_is_allowed_only_for_clarification(baseline):
    client = ScriptedClient(tool="clarify")
    original = client.structured

    def empty_evidence(schema, system, data, prompt_version):
        if schema is IntentDecision:
            return IntentDecision(tool="clarify", evidence=""), {}
        return original(schema, system, data, prompt_version)

    client.structured = empty_evidence
    _, _, out = start(baseline, client, text="Merhaba")
    question = pause(out)
    assert question["kind"] == "question"
    assert "Planı incelemek" in question["questions"][0]


class ChattyClient(ScriptedClient):
    """Router says clarify (small talk); the reply step answers with the given text."""

    def __init__(self, reply):
        super().__init__(tool="clarify")
        self.reply = reply

    def structured(self, schema, system, data, prompt_version):
        from core.llm.reply import Reply

        if schema is IntentDecision:
            return IntentDecision(tool="clarify", evidence=""), {"test_double": True}
        if schema is Reply:
            if self.reply is None:
                raise ModelUnavailable("reply model offline")
            return Reply(text=self.reply), {"prompt_version": prompt_version}
        return super().structured(schema, system, data, prompt_version)


def test_small_talk_gets_a_reply_before_the_intent_question(baseline):
    reply = "İyiyim, teşekkürler! Planı mı inceleyelim, yeni sipariş mi ekleyelim?"
    graph, config, out = start(baseline, ChattyClient(reply), text="naber")
    question = pause(out)
    assert question["kind"] == "question" and question["reply"] == reply
    assert question["choices"] == ["planı incele", "yeni sipariş ekle"]
    assert out["reply_metadata"]["prompt_version"] == "conversation-reply-v1"


def test_reply_with_numbers_is_dropped_for_the_plain_question(baseline):
    _, _, out = start(baseline, ChattyClient("Planda 10 iş var."), text="naber")
    assert pause(out)["reply"] is None
    assert out["reply_metadata"]["fallback_reason"] == "reply contained a number"


def test_without_reply_model_the_plain_question_stays(baseline):
    _, _, out = start(baseline, ChattyClient(None), text="naber")
    assert pause(out)["reply"] is None
    assert pause(out)["questions"] == [
        "Planı incelemek mi, yeni sipariş eklemek mi istiyorsunuz?"
    ]


def test_only_the_next_question_is_asked(baseline):
    _, _, out = start(
        baseline,
        ScriptedClient(duration=None),
        text="Yeni sipariş: Torna 1 üzerinde tornalama, yarın teslim.",
    )
    questions = pause(out)["questions"]
    assert len(questions) == 1 and "süresi" in questions[0]


class UnsureClient(ScriptedClient):
    """Fields without a duration; every follow-up interpretation is invalid."""

    def structured(self, schema, system, data, prompt_version):
        from core.llm.conversation import FieldAnswer

        if schema is FieldAnswer:
            raise InvalidModelOutput("not grounded")
        return super().structured(schema, system, data, prompt_version)


def test_unvalidated_answer_repeats_the_question_and_keeps_the_draft(baseline):
    graph, config, out = start(
        baseline,
        UnsureClient(duration=None),
        text="Yeni sipariş: Torna 1 üzerinde tornalama.",
    )
    out = graph.invoke(Command(resume="bunu ekle"), config)
    question = pause(out)
    assert question["kind"] == "question"
    assert question["questions"][0].startswith("Bu cevabı anlayamadım.")
    out = graph.invoke(Command(resume="10 dakika"), config)
    assert pause(out)["kind"] == "confirmation"

"""Tool authority and conversational routing contracts, using model test doubles."""

from pathlib import Path

import pytest

from benchmarks.workshop_order_demo import DemoInput
from core.llm.conversation import (
    FieldAnswer,
    PolicyAnswer,
    answer_intake,
    begin_intake,
)
from core.llm.tools import execute_tool, render_inspection, tool_catalog
from core.llm.explanation import FactSelection, explain_inspection
from core.scenarios import create_snapshot
from tests.test_conversation import ScriptedClient, fields


@pytest.fixture
def baseline():
    demo = DemoInput.model_validate_json(
        Path("data/examples/order_demo.json").read_text()
    )
    return create_snapshot(demo.baseline, "v1", 2)


def test_workload_tool_uses_actual_snapshot_without_modifying_it(baseline):
    before = baseline.model_dump()
    result = execute_tool("inspect_plan", {"query": "kaç iş var?"}, baseline)
    assert result["workload"]["total_job_count"] == 2
    assert result["workload"]["unfinished_job_count"] == 2
    assert result["workload"]["not_started_job_count"] == 1
    assert result["workload"]["operation_counts"] == {
        "completed": 1,
        "in_progress": 1,
        "not_started": 1,
    }
    assert "2 iş var" in render_inspection(result)
    assert baseline.model_dump() == before


def test_unknown_tool_and_model_supplied_approval_are_rejected(baseline):
    with pytest.raises(ValueError, match="Unknown"):
        execute_tool("run_sql", {"query": "DROP TABLE jobs"}, baseline)
    proposal = begin_intake(
        "Yeni sipariş Torna 1 üzerinde 10 dakika.", baseline, ScriptedClient(fields())
    )
    arguments = {"intake": proposal.result.model_dump(), "scenario_id": "new"}
    with pytest.raises(ValueError, match="confirmation"):
        execute_tool("simulate_order", arguments, baseline)
    with pytest.raises(ValueError):
        execute_tool("simulate_order", {**arguments, "user_confirmed": True}, baseline)
    assert (
        execute_tool(
            "simulate_order", arguments, baseline, user_confirmed=True
        ).result.status
        == "OPTIMAL"
    )


def test_information_request_can_mention_new_order(baseline):
    text = "Yeni sipariş vermek için ne kadar sipariş var ön tarafta"
    client = ScriptedClient(tool="inspect_plan", evidence="ne kadar sipariş var")
    result = begin_intake(text, baseline, client)
    assert result.result.state == "inspection"
    assert result.audit[-1]["stage"] == "tool_execution"
    assert client.calls == ["IntentDecision"]


def test_natural_intent_followup_is_routed_with_history(baseline):
    class ContextClient(ScriptedClient):
        def structured(self, schema, system, data, prompt_version):
            if len(self.calls) == 1:
                assert data["messages"] == ["Ne yapalım?", "planı incelemek istiyorum"]
                assert {t["name"] for t in data["tools"]} == {
                    t["name"] for t in tool_catalog()
                }
                self.tool, self.evidence = "inspect_plan", "planı incelemek istiyorum"
            return super().structured(schema, system, data, prompt_version)

    client = ContextClient(tool="clarify", evidence="Ne yapalım")
    original = begin_intake("Ne yapalım?", baseline, client)
    result = answer_intake(original, "planı incelemek istiyorum", baseline, client)
    assert result.result.state == "inspection"
    assert original.messages == ["Ne yapalım?"]
    assert client.calls == ["IntentDecision", "IntentDecision"]


class FieldClient(ScriptedClient):
    def __init__(self, initial_fields, value, evidence, action="answer_field"):
        super().__init__(initial_fields)
        self.answer_value, self.answer_evidence, self.action = value, evidence, action

    def structured(self, schema, system, data, prompt_version):
        if schema in (FieldAnswer, PolicyAnswer):
            self.calls.append(schema.__name__)
            if schema is PolicyAnswer:
                return PolicyAnswer(action=self.action, value=self.answer_value), {
                    "test_double": True
                }
            return FieldAnswer(
                action=self.action,
                value=self.answer_value,
                evidence=self.answer_evidence,
            ), {"test_double": True}
        return super().structured(schema, system, data, prompt_version)


@pytest.mark.parametrize(
    "missing,reply,value,expected",
    [
        ("duration", "bu işlem on dakika sürer", "on dakika", {100: 10}),
        ("machine", "Torna 2 olsun lütfen", "Torna 2", {200: 10}),
    ],
)
def test_natural_field_answer_changes_only_pending_slot(
    baseline, missing, reply, value, expected
):
    initial_fields = (
        fields(duration=None) if missing == "duration" else fields(machine=None)
    )
    text = (
        "Yeni sipariş Torna 1 üzerinde işlem."
        if missing == "duration"
        else "Yeni sipariş 10 dakika işlem."
    )
    client = FieldClient(initial_fields, value, value)
    original = begin_intake(text, baseline, client)
    result = answer_intake(original, reply, baseline, client)
    assert result.result.state == "confirmation_required"
    assert result.result.proposed_order.operations[0].processing_times == expected
    assert original.result.state == "clarification"


def test_followup_hallucination_is_rejected(baseline):
    client = FieldClient(fields(duration=None), "99 dakika", "on dakika")
    session = begin_intake("Yeni sipariş Torna 1 üzerinde işlem.", baseline, client)
    result = answer_intake(session, "bu işlem on dakika sürer", baseline, client)
    assert result.result.state == "invalid_model_output"
    assert result.draft.operations[0].options[0].duration_text is None


def test_natural_preservation_answer_retains_user_evidence(baseline):
    client = FieldClient(
        fields(preservation="ambiguous", preservation_text="Mevcut işleri geciktirme"),
        "mevcut bitişler",
        "şu anki bitiş zamanları değişmesin",
    )
    session = begin_intake(
        "Yeni sipariş Torna 1 üzerinde 10 dakika. Mevcut işleri geciktirme.",
        baseline,
        client,
    )
    result = answer_intake(
        session, "şu anki bitiş zamanları değişmesin", baseline, client
    )
    assert result.result.state == "confirmation_required"
    assert result.result.preserve_existing_completions is True


def test_field_followup_can_switch_to_read_only_inspection(baseline):
    client = FieldClient(
        fields(duration=None), None, "önce planı göster", action="inspect_plan"
    )
    session = begin_intake("Yeni sipariş Torna 1 üzerinde işlem.", baseline, client)
    result = answer_intake(session, "önce planı göster", baseline, client)
    assert result.result.state == "inspection"
    assert result.result.proposed_order is None


def test_navigation_binds_actual_reply_without_requiring_an_extracted_value(baseline):
    client = FieldClient(fields(duration=None), None, None, action="inspect_plan")
    session = begin_intake("Yeni sipariş Torna 1 üzerinde işlem.", baseline, client)
    result = answer_intake(
        session, "Önce mevcut planı gösterir misin?", baseline, client
    )
    assert result.result.state == "inspection"
    assert result.audit[-1]["arguments"]["query"] == "Önce mevcut planı gösterir misin?"


def test_navigation_cannot_smuggle_a_field_update(baseline):
    client = FieldClient(
        fields(duration=None), "99 dakika", None, action="inspect_plan"
    )
    session = begin_intake("Yeni sipariş Torna 1 üzerinde işlem.", baseline, client)
    result = answer_intake(session, "önce planı göster", baseline, client)
    assert result.result.state == "invalid_model_output"
    assert result.draft.operations[0].options[0].duration_text is None


def test_inspection_explanation_uses_tool_facts_and_falls_back_on_invention(baseline):
    from tests.test_gemma_service import FakeClient

    inspection = execute_tool("inspect_plan", {"query": "kaç iş var"}, baseline)
    result = explain_inspection(
        "kaç iş var", inspection, FakeClient(FactSelection(fact_ids=["workload"]))
    )
    assert result.origin == "gemma_selected_facts"
    assert "2 iş var" in result.text
    invalid = explain_inspection(
        "kaç iş var", inspection, FakeClient(FactSelection(fact_ids=["999_jobs"]))
    )
    assert invalid.origin == "computed_fallback"
    assert "999" not in invalid.text
    assert "Plan değiştirilmedi" in invalid.text


def test_offered_intent_choice_does_not_loop_when_the_model_says_clarify(baseline):
    client = ScriptedClient(
        fields(machine=None, duration=None), tool="clarify", evidence=""
    )
    session = begin_intake("merhaba", baseline, client)
    assert session.pending[0].kind == "intent"
    order = answer_intake(session, "yeni sipariş ekle", baseline, client)
    assert order.result.tool == "simulate_order"
    assert order.pending[0].kind != "intent"
    inspection = answer_intake(session, "Planı incele", baseline, client)
    assert inspection.result.state == "inspection"


def test_inspection_answer_always_states_counts_and_finish(baseline):
    from tests.test_gemma_service import FakeClient

    inspection = execute_tool("inspect_plan", {"query": "planı incele"}, baseline)
    result = explain_inspection(
        "planı incele", inspection, FakeClient(FactSelection(fact_ids=["scope"]))
    )
    assert result.origin == "gemma_selected_facts"
    assert result.text.startswith("Yüklü planda 2 iş var")
    assert "Planın son bitişi" in result.text

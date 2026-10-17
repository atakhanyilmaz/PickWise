"""Unit-test slot safety with scripted responses; real Gemma is evaluated separately."""

from pathlib import Path

import pytest

from benchmarks.workshop_order_demo import DemoInput
from core.llm.conversation import (
    IntentDecision,
    OrderFields,
    answer_intake,
    begin_intake,
)
from core.llm.intake import _minutes, confirm_and_simulate
from core.llm.ollama_client import ModelUnavailable
from core.scenarios import create_snapshot


@pytest.fixture
def baseline():
    demo = DemoInput.model_validate_json(
        Path("data/examples/order_demo.json").read_text()
    )
    return create_snapshot(demo.baseline, "v1", 2)


class ScriptedClient:
    def __init__(self, fields=None, tool="simulate_order", evidence="Yeni sipariş"):
        self.fields = fields
        self.tool = tool
        self.evidence = evidence
        self.calls = []

    def structured(self, schema, system, data, prompt_version):
        self.calls.append(schema.__name__)
        if schema is IntentDecision:
            value = IntentDecision(tool=self.tool, evidence=self.evidence)
        else:
            value = OrderFields.model_validate(self.fields)
        return value, {"test_double": True, "prompt_version": prompt_version}


def fields(machine="Torna 1", duration="10 dakika", **extra):
    result = dict(
        order_name=None,
        operations=[
            {
                "name": "İşlem",
                "options": [{"machine_text": machine, "duration_text": duration}],
            }
        ],
        deadline_kind="none",
        deadline_text=None,
        preservation="none",
        preservation_text=None,
    )
    result.update(extra)
    return result


def test_intent_and_fields_are_separate_calls(baseline):
    client = ScriptedClient(fields())
    session = begin_intake("Yeni sipariş Torna 1 üzerinde 10 dakika.", baseline, client)
    assert client.calls == ["IntentDecision", "OrderFields"]
    assert session.result.state == "confirmation_required"


def test_missing_duration_followup_never_reextracts_known_fields(baseline):
    client = ScriptedClient(fields(duration=None))
    start = begin_intake("Yeni sipariş Torna 1 üzerinde işlem.", baseline, client)
    original = start.model_dump()
    finished = answer_intake(start, "iki saat", baseline)
    assert finished.result.state == "confirmation_required"
    assert finished.result.proposed_order.operations[0].processing_times == {100: 120}
    assert start.model_dump() == original
    assert client.calls == ["IntentDecision", "OrderFields"]
    assert finished.draft.operations[0].options[0].machine_text == "Torna 1"


def test_ambiguous_machine_options_and_followup(baseline):
    session = begin_intake(
        "Yeni sipariş torna üzerinde 10 dakika.",
        baseline,
        ScriptedClient(fields(machine="torna")),
    )
    assert session.pending[0].kind == "machine"
    assert session.pending[0].choices == ["Torna 1", "Torna 2"]
    finished = answer_intake(session, "Torna 2", baseline)
    assert finished.result.proposed_order.operations[0].processing_times == {200: 10}


def test_hallucinated_machine_must_be_corrected_not_accepted(baseline):
    session = begin_intake(
        "Yeni sipariş torna üzerinde 10 dakika.",
        baseline,
        ScriptedClient(fields(machine="Torna 1")),
    )
    assert session.result.state == "clarification"
    assert session.result.proposed_order is None
    assert session.pending[0].kind == "machine"


def test_partial_number_evidence_cannot_pass(baseline):
    session = begin_intake(
        "Yeni sipariş Torna 1 üzerinde 110 dakika.",
        baseline,
        ScriptedClient(fields(duration="10 dakika")),
    )
    assert session.result.state == "clarification"
    assert session.pending[0].kind == "duration"


def test_invalid_answer_preserves_every_field(baseline):
    session = begin_intake(
        "Yeni sipariş Torna 1 üzerinde işlem.",
        baseline,
        ScriptedClient(fields(duration=None)),
    )
    after = answer_intake(session, "çok hızlı yap", baseline)
    assert after.result.state == "clarification"
    assert after.draft == session.draft
    assert after.messages == session.messages


def test_multiple_operations_only_targeted_duration_changes(baseline):
    values = fields()
    values["operations"].append(
        {
            "name": "İkinci işlem",
            "options": [{"machine_text": "Torna 2", "duration_text": None}],
        }
    )
    text = "Yeni sipariş: Torna 1 üzerinde 10 dakika, sonra Torna 2."
    session = begin_intake(text, baseline, ScriptedClient(values))
    assert session.pending[0].operation_index == 1
    result = answer_intake(session, "beş dakika", baseline)
    assert result.result.proposed_order.operations[0].processing_times == {100: 10}
    assert result.result.proposed_order.operations[1].processing_times == {200: 5}


def test_date_is_not_guessed_and_can_be_replaced_explicitly(baseline):
    text = "Yeni sipariş Torna 1 üzerinde 10 dakika. Yarın sabah teslim."
    session = begin_intake(
        text, baseline, ScriptedClient(fields(deadline_kind="ambiguous"))
    )
    assert session.pending[0].kind == "deadline_kind"
    session = answer_intake(session, "sert", baseline)
    assert session.pending[0].kind == "deadline"
    session = answer_intake(session, "t=40 dakika", baseline)
    assert session.result.state == "confirmation_required"
    assert session.result.proposed_order.deadline == 40
    assert session.resolved_time is True


def test_user_can_explicitly_remove_deadline(baseline):
    session = begin_intake(
        "Yeni sipariş Torna 1 üzerinde 10 dakika. Yarın teslim.",
        baseline,
        ScriptedClient(fields(deadline_kind="ambiguous")),
    )
    session = answer_intake(session, "termin yok", baseline)
    assert session.result.state == "confirmation_required"
    assert session.result.proposed_order.deadline is None


def test_protection_meaning_answer_reaches_simulation(baseline):
    text = "Yeni sipariş Torna 1 üzerinde 10 dakika. Sert termin t=20 dakika. Mevcut işleri geciktirme."
    session = begin_intake(
        text,
        baseline,
        ScriptedClient(
            fields(
                deadline_kind="hard",
                deadline_text="t=20 dakika",
                preservation="ambiguous",
                preservation_text="Mevcut işleri geciktirme",
            )
        ),
    )
    session = answer_intake(session, "mevcut bitişler", baseline)
    assert session.result.state == "confirmation_required"
    result = confirm_and_simulate(
        session.result, baseline, "protected", user_confirmed=True
    )
    assert result.result.status == "INFEASIBLE"


def test_followup_requires_same_plan_contents_not_just_version(baseline):
    session = begin_intake(
        "Yeni sipariş Torna 1 üzerinde işlem.",
        baseline,
        ScriptedClient(fields(duration=None)),
    )
    changed = baseline.model_copy(deep=True)
    changed.scenario.description = "changed"
    with pytest.raises(ValueError, match="Baseline changed"):
        answer_intake(session, "10 dakika", changed)


def test_inspection_does_not_call_field_extractor(baseline):
    client = ScriptedClient(tool="inspect_plan", evidence="Planı incele")
    result = begin_intake("Planı incele", baseline, client)
    assert result.result.inspection["makespan"] == 15
    assert client.calls == ["IntentDecision"]


def test_unsupported_downtime_does_not_call_model(baseline):
    client = ScriptedClient()
    result = begin_intake("Torna 1 duruş ekle", baseline, client)
    assert result.result.state == "unsupported"
    assert client.calls == []


def test_model_unavailable_does_not_create_draft(baseline):
    class Offline:
        def structured(self, *args):
            raise ModelUnavailable("offline")

    result = begin_intake("Yeni sipariş", baseline, Offline())
    assert result.result.state == "model_unavailable"
    assert result.draft is None


def test_confirmation_cannot_be_replaced_with_followup_evet(baseline):
    session = begin_intake(
        "Yeni sipariş Torna 1 üzerinde 10 dakika.", baseline, ScriptedClient(fields())
    )
    with pytest.raises(ValueError):
        answer_intake(session, "evet", baseline)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("iki saat", 120),
        ("bir buçuk saat", 90),
        ("yarım saat", 30),
        ("yirmi beş dakika", 25),
        ("1,5 saat", 90),
        ("on bir dk", 11),
    ],
)
def test_number_conversion_is_code_based(text, expected):
    assert _minutes(text) == expected


def test_ambiguous_intent_can_be_answered_without_reclassifying(baseline):
    client = ScriptedClient(tool="clarify", evidence="Ne yapalım")
    session = begin_intake("Ne yapalım?", baseline, client)
    assert session.pending[0].kind == "intent"
    result = answer_intake(session, "planı incele", baseline)
    assert result.result.state == "inspection"
    assert result.result.inspection["makespan"] == 15
    assert client.calls == ["IntentDecision"]


def test_intent_followup_retains_original_order_details(baseline):
    client = ScriptedClient(fields(), tool="clarify", evidence="Torna 1")
    session = begin_intake("Torna 1 üzerinde 10 dakika işlem.", baseline, client)
    result = answer_intake(session, "yeni sipariş ekle", baseline, client)
    assert result.result.state == "confirmation_required"
    assert result.result.proposed_order.operations[0].processing_times == {100: 10}
    assert client.calls == ["IntentDecision", "OrderFields"]


def test_invalid_name_after_missing_duration_is_rejected_without_crash(baseline):
    client = ScriptedClient(fields(duration=None, order_name="uydurma isim"))
    session = begin_intake("Yeni sipariş Torna 1 üzerinde işlem.", baseline, client)
    result = answer_intake(session, "10 dakika", baseline)
    assert result.result.state == "invalid_model_output"
    assert result.result.proposed_order is None


def test_imported_pending_slot_out_of_range_is_rejected(baseline):
    session = begin_intake(
        "Yeni sipariş Torna 1 üzerinde işlem.",
        baseline,
        ScriptedClient(fields(duration=None)),
    )
    session.pending[0].operation_index = 999
    with pytest.raises(ValueError, match="indices"):
        answer_intake(session, "10 dakika", baseline)


def test_operations_followup_preserves_existing_deadline(baseline):
    from core.llm.conversation import OperationsAnswer

    class OperationsClient(ScriptedClient):
        def structured(self, schema, system, data, prompt_version):
            if schema is OperationsAnswer:
                self.calls.append(schema.__name__)
                return OperationsAnswer(operations=fields()["operations"]), {
                    "test_double": True
                }
            return super().structured(schema, system, data, prompt_version)

    values = fields(operations=[], deadline_kind="hard", deadline_text="t=40 dakika")
    client = OperationsClient(values)
    session = begin_intake("Yeni sipariş. Sert termin t=40 dakika.", baseline, client)
    assert session.pending[0].kind == "operations"
    session = answer_intake(session, "Torna 1 üzerinde 10 dakika.", baseline, client)
    assert session.result.state == "confirmation_required"
    assert session.result.proposed_order.deadline == 40

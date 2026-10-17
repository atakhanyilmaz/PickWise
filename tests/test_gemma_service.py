"""Contract and safety tests use fake responses, not a real-model quality claim."""

from pathlib import Path

import pytest

from benchmarks.workshop_order_demo import DemoInput
from core.domain_rules import RouteSource, WorkshopScenario
from core.llm.explanation import FactSelection, explain_simulation
from core.llm.intake import (
    IntakeDraft,
    confirm_and_simulate,
    extract_order,
    interpret_draft,
)
from core.llm.ollama_client import InvalidModelOutput, ModelUnavailable, OllamaClient
from core.scenarios import OrderRequest, create_snapshot, simulate_order
from core.workshop_fjsp_builder import build_env


@pytest.fixture
def baseline():
    demo = DemoInput.model_validate_json(
        Path("data/examples/order_demo.json").read_text()
    )
    return create_snapshot(demo.baseline, "v1", 2)


def draft(**changes):
    data = dict(
        tool="simulate_order",
        order_name=None,
        operations=[
            {
                "name": "Tornalama",
                "options": [{"machine_text": "Torna 1", "duration_text": "10 dakika"}],
            }
        ],
        deadline_kind="hard",
        deadline_text="t=20 dakika",
        preservation="none",
        preservation_text=None,
        unsupported_constraints=[],
    )
    data.update(changes)
    return IntakeDraft.model_validate(data)


TEXT = "Yeni sipariş: Torna 1 üzerinde 10 dakika tornalama. Sert termin t=20 dakika."


class FakeClient:
    def __init__(self, output=None, error=None):
        self.output, self.error = output, error

    def structured(self, schema, system, data, prompt_version):
        if self.error:
            raise self.error
        return self.output, {"prompt_version": prompt_version, "test_double": True}


def test_model_extraction_requires_explicit_human_confirmation(baseline):
    old = baseline.model_dump()
    intake = extract_order(TEXT, baseline, FakeClient(draft()))
    assert intake.state == "confirmation_required"
    assert intake.proposed_order.route_source == RouteSource.USER_PROPOSED
    with pytest.raises(ValueError, match="confirmation"):
        confirm_and_simulate(intake, baseline, "s2", user_confirmed=False)
    result = confirm_and_simulate(
        intake, baseline, "s2", user_confirmed=True, time_limit=2
    )
    assert result.result.makespan == 25
    assert baseline.model_dump() == old
    assert intake.proposed_order.route_source == RouteSource.USER_PROPOSED


def test_proposed_route_cannot_bypass_approval(baseline):
    intake = interpret_draft(TEXT, baseline, draft())
    data = baseline.scenario.model_dump()
    data["jobs"].append(intake.proposed_order.model_dump())
    with pytest.raises(ValueError, match="USER_PROPOSED"):
        build_env(WorkshopScenario.model_validate(data), approved_only=False)


def test_missing_duration_clarifies_instead_of_guessing(baseline):
    output = draft(
        operations=[
            {
                "name": "Tornalama",
                "options": [{"machine_text": "Torna 1", "duration_text": None}],
            }
        ],
        deadline_kind="none",
        deadline_text=None,
    )
    result = interpret_draft(
        "Yeni sipariş Torna 1 üzerinde tornalama.", baseline, output
    )
    assert result.state == "clarification"
    assert result.proposed_order is None
    assert any("süresi" in q for q in result.questions)


@pytest.mark.parametrize(
    "machine, duration", [("Torna 9", "10 dakika"), ("Torna 1", "99 dakika")]
)
def test_model_cannot_invent_machine_or_duration_evidence(baseline, machine, duration):
    output = draft(
        operations=[
            {
                "name": "Tornalama",
                "options": [{"machine_text": machine, "duration_text": duration}],
            }
        ]
    )
    result = extract_order(TEXT, baseline, FakeClient(output))
    assert result.state == "invalid_model_output"
    assert result.proposed_order is None


def test_ambiguous_machine_is_not_resolved_by_similarity(baseline):
    output = draft(
        operations=[
            {
                "name": "Tornalama",
                "options": [{"machine_text": "torna", "duration_text": "10 dakika"}],
            }
        ],
        deadline_kind="none",
        deadline_text=None,
    )
    result = interpret_draft("Yeni sipariş torna üzerinde 10 dakika.", baseline, output)
    assert result.state == "clarification"
    assert any("benzersiz" in q for q in result.questions)


@pytest.mark.parametrize("word", ["yarın sabah", "mola", "duruş", "ücret"])
def test_unsupported_constraint_cannot_be_silently_dropped(baseline, word):
    result = interpret_draft(TEXT + " " + word, baseline, draft())
    assert result.state == "unsupported"
    assert result.proposed_order is None


def test_ambiguous_deadline_kind_requires_question(baseline):
    result = interpret_draft(TEXT, baseline, draft(deadline_kind="ambiguous"))
    assert result.state == "clarification"
    assert any("sert" in q for q in result.questions)


def test_deadline_mentioned_but_omitted_by_model_requires_question(baseline):
    result = interpret_draft(
        TEXT, baseline, draft(deadline_kind="none", deadline_text=None)
    )
    assert result.state == "clarification"


def test_preserve_request_requires_meaning_clarification(baseline):
    result = interpret_draft(
        TEXT + " Mevcut işleri geciktirme.",
        baseline,
        draft(preservation="ambiguous", preservation_text="Mevcut işleri geciktirme"),
    )
    assert result.state == "clarification"
    assert any("bitişleri mi" in q for q in result.questions)


def test_existing_completions_protection_reaches_solver(baseline):
    result = interpret_draft(
        TEXT + " Mevcut bitişleri koru.",
        baseline,
        draft(preservation="completions", preservation_text="Mevcut bitişleri koru"),
    )
    simulated = confirm_and_simulate(result, baseline, "protected", user_confirmed=True)
    assert simulated.result.status == "INFEASIBLE"


def test_hour_unit_conversion_is_explicit(baseline):
    result = interpret_draft(
        "Yeni sipariş Torna 1 üzerinde 1 saat.",
        baseline,
        draft(
            operations=[
                {
                    "name": "İşlem",
                    "options": [{"machine_text": "Torna 1", "duration_text": "1 saat"}],
                }
            ],
            deadline_kind="none",
            deadline_text=None,
        ),
    )
    assert result.proposed_order.operations[0].processing_times == {100: 60}


def test_user_approved_soft_deadline_is_reported_not_hard(baseline):
    result = interpret_draft(TEXT, baseline, draft(deadline_kind="soft"))
    assert result.proposed_order.deadline is None
    assert result.proposed_order.due_date == 20


def test_invalid_model_and_unavailable_model_are_distinct(baseline):
    for error, state in [
        (ModelUnavailable("offline"), "model_unavailable"),
        (InvalidModelOutput("bad schema"), "invalid_model_output"),
    ]:
        result = extract_order(TEXT, baseline, FakeClient(error=error))
        assert result.state == state
        assert result.proposed_order is None


def test_inspection_uses_computed_plan_metrics(baseline):
    output = draft(
        tool="inspect_plan", operations=[], deadline_kind="none", deadline_text=None
    )
    result = interpret_draft("Planı incele", baseline, output)
    assert result.state == "inspection"
    assert result.inspection["makespan"] == 15


def test_inspect_misclassification_cannot_execute_order(baseline):
    result = interpret_draft(TEXT, baseline, draft(tool="inspect_plan"))
    assert result.state == "clarification"
    assert result.proposed_order is None


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "http://192.168.1.2:11434",
        "http://localhost:11434/api",
        "http://user:password@localhost:11434",
    ],
)
def test_adapter_rejects_remote_or_credential_endpoints(url):
    with pytest.raises(ValueError):
        OllamaClient(base_url=url)


def simulation(baseline):
    demo = DemoInput.model_validate_json(
        Path("data/examples/order_demo.json").read_text()
    )
    return simulate_order(
        baseline,
        OrderRequest(
            baseline_version_id="v1",
            scenario_id="s2",
            order=demo.new_order,
            allow_demo=True,
            time_limit_seconds=2,
        ),
    )


def test_explanation_only_uses_allowed_computed_facts(baseline):
    result = explain_simulation(
        simulation(baseline), FakeClient(FactSelection(fact_ids=["makespan"]))
    )
    assert result.origin == "gemma_selected_facts"
    assert "15 dakikadan 25 dakikaya" in result.text
    assert "5 dakika" in result.text
    assert "optimum" in result.text


def test_hallucinated_explanation_falls_back_to_computed_text(baseline):
    result = explain_simulation(
        simulation(baseline), FakeClient(FactSelection(fact_ids=["savings_99_percent"]))
    )
    assert result.origin == "computed_fallback"
    assert "99" not in result.text
    assert "15 dakikadan 25 dakikaya" in result.text


def test_manual_planning_and_explanation_without_model(baseline):
    result = explain_simulation(simulation(baseline))
    assert result.origin == "computed_fallback"
    assert "başlangıç planı değiştirilmedi" in result.text


@pytest.mark.parametrize("value", [False, "evet", "false", 1, None])
def test_confirmation_requires_actual_boolean_true(baseline, value):
    intake = interpret_draft(TEXT, baseline, draft())
    with pytest.raises(ValueError):
        confirm_and_simulate(intake, baseline, "s2", user_confirmed=value)


def test_cloud_backed_model_is_rejected(monkeypatch):
    client = OllamaClient()

    def response(path, payload=None):
        if path == "/api/tags":
            return {"models": [{"name": "gemma4:e2b", "digest": "fake"}]}
        return {"remote_host": "https://cloud.example", "details": {"family": "gemma"}}

    monkeypatch.setattr(client, "_request", response)
    with pytest.raises(ModelUnavailable, match="Cloud"):
        client.metadata()


def test_non_gemma_model_rejected(monkeypatch):
    client = OllamaClient("other")

    def response(path, payload=None):
        if path == "/api/tags":
            return {"models": [{"name": "other", "digest": "fake"}]}
        return {
            "details": {"family": "other"},
            "model_info": {"general.architecture": "other"},
        }

    monkeypatch.setattr(client, "_request", response)
    with pytest.raises(ModelUnavailable, match="Gemma"):
        client.metadata()

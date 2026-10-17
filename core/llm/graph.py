"""LangGraph wrapper around the existing Gemma order flow.

The graph adds only the human pauses; every decision stays in the tested functions it calls:

    intake ─▶ clarify ↺ ─▶ confirm ─▶ simulate ─▶ explain
       └──────────┴──────────┴─▶ stop (unsupported, inspection answer, model error, declined)

Usage:

    graph = build_order_graph(baseline, client)
    config = {"configurable": {"thread_id": "user-1"}}
    out = graph.invoke({"text": "Yeni sipariş: Torna 1 üzerinde tornalama"}, config)
    out["__interrupt__"][0].value             # question or proposal for the user
    out = graph.invoke(Command(resume="iki saat"), config)  # answer a question
    out = graph.invoke(Command(resume=True), config)        # approve the proposal

`explanation` is an Explanation dump: text, origin (Gemma-selected or computed
fallback), selected fact ids and model metadata.

State holds plain JSON (model_dump(mode="json")) so the checkpointer stores no custom classes;
nodes revalidate it with the Pydantic models on every read. Nothing is saved to SQLite.
"""

from typing import TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from core.llm.conversation import IntakeSession, answer_intake, begin_intake
from core.llm.explanation import explain_inspection, explain_simulation
from core.llm.intake import confirm_and_simulate
from core.pipeline import dispatch
from core.scenarios import PlanSnapshot, SimulationResult


class OrderState(TypedDict, total=False):
    text: str
    session: dict
    approved: bool
    simulation: dict
    dispatch: list[dict]
    explanation: dict
    message: str


def _session(state):
    return IntakeSession.model_validate(state["session"])


def _next_after_intake(state):
    return {
        "clarification": "clarify",
        "confirmation_required": "confirm",
    }.get(_session(state).result.state, "stop")


def build_order_graph(
    baseline: PlanSnapshot,
    client,
    *,
    scenario_id="gemma_order",
    time_limit=10,
    checkpointer=None,
):
    """Compile the order graph for one baseline plan and one model client."""

    def intake(state):
        return {
            "session": begin_intake(state["text"], baseline, client).model_dump(
                mode="json"
            )
        }

    def clarify(state):
        session = _session(state)
        answer = interrupt(
            {
                "kind": "question",
                "questions": session.result.questions,
                "choices": session.pending[0].choices if session.pending else [],
            }
        )
        return {
            "session": answer_intake(session, answer, baseline, client).model_dump(
                mode="json"
            )
        }

    def confirm(state):
        result = _session(state).result
        decision = interrupt(
            {
                "kind": "confirmation",
                "order": result.proposed_order.model_dump(mode="json"),
                "preserve_existing_completions": result.preserve_existing_completions,
            }
        )
        return {"approved": decision is True}

    def simulate(state):
        simulation = confirm_and_simulate(
            _session(state).result,
            baseline,
            scenario_id,
            user_confirmed=True,
            time_limit=time_limit,
        )
        statuses = (
            dispatch(
                simulation.scenario,
                simulation.result,
                simulation.scenario.current_time,
            )
            if simulation.comparison
            else []
        )
        return {
            "simulation": simulation.model_dump(mode="json"),
            "dispatch": [status.model_dump(mode="json") for status in statuses],
        }

    def explain(state):
        simulation = SimulationResult.model_validate(state["simulation"])
        return {
            "explanation": explain_simulation(simulation, client).model_dump(
                mode="json"
            )
        }

    def stop(state):
        if state.get("approved") is False:
            return {"message": "Onay verilmedi; simülasyon çalıştırılmadı."}
        result = _session(state).result
        if result.state == "inspection":
            answer = explain_inspection(result.user_text, result.inspection, client)
            return {"message": answer.text}
        return {"message": " ".join(result.questions)}

    graph = StateGraph(OrderState)
    for name, node in [
        ("intake", intake),
        ("clarify", clarify),
        ("confirm", confirm),
        ("simulate", simulate),
        ("explain", explain),
        ("stop", stop),
    ]:
        graph.add_node(name, node)
    graph.add_edge(START, "intake")
    graph.add_conditional_edges("intake", _next_after_intake)
    graph.add_conditional_edges("clarify", _next_after_intake)
    graph.add_conditional_edges(
        "confirm", lambda state: "simulate" if state["approved"] else "stop"
    )
    graph.add_edge("simulate", "explain")
    graph.add_edge("explain", END)
    graph.add_edge("stop", END)
    return graph.compile(checkpointer=checkpointer or InMemorySaver())

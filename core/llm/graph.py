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

`reply` is a short conversational answer (core/llm/reply.py) shown before the intent
question or an unsupported-request note; it never contains plan facts.

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
from core.llm.reply import conversational_reply
from core.llm.tools import execute_tool
from core.pipeline import dispatch
from core.scenarios import PlanSnapshot, SimulationResult


class OrderState(TypedDict, total=False):
    text: str
    session: dict
    approved: bool
    simulation: dict
    inspection: dict
    dispatch: list[dict]
    explanation: dict
    message: str
    reply: str | None
    reply_metadata: dict


def _session(state):
    return IntakeSession.model_validate(state["session"])


def _next_after_intake(state):
    return {
        "clarification": "clarify",
        "confirmation_required": "confirm",
    }.get(_session(state).result.state, "stop")


def _needs_reply(session):
    """Small talk or an off-topic message: the router asked what the user wants
    (intent question) or found no tool for it. Code-rule refusals keep their text."""
    result = session.result
    if result.state == "clarification":
        return bool(session.pending) and session.pending[0].kind == "intent"
    return (
        result.state == "unsupported"
        and bool(session.audit)
        and session.audit[-1].get("stage") == "intent"
    )


def _current_questions(session):
    """Only what the next answer fills: the service lists every open field, but an
    answer goes to the first pending one. Notes printed before that question stay."""
    questions = session.result.questions
    if not session.pending:
        return questions
    current = session.pending[0].question
    for index, question in enumerate(questions):
        if question.endswith(current):
            return questions[: index + 1]
    return questions


def _retry(previous, failed):
    """Keep the draft and ask the same field again when an answer could not be
    validated, instead of ending the conversation; the failed stage stays audited."""
    session = previous.model_copy(deep=True)
    session.audit = failed.audit
    session.result.questions = [
        "Bu cevabı anlayamadım. " + previous.pending[0].question
    ]
    return session


def build_order_graph(
    baseline: PlanSnapshot,
    client,
    *,
    scenario_id="gemma_order",
    time_limit=10,
    checkpointer=None,
):
    """Compile the order graph for one baseline plan and one model client."""

    def with_reply(session, text):
        """Session update plus a conversational reply when the message was not a request."""
        reply, metadata = (
            conversational_reply(text, session.messages, client)
            if _needs_reply(session)
            else (None, {})
        )
        return {
            "session": session.model_dump(mode="json"),
            "reply": reply,
            "reply_metadata": metadata,
        }

    def intake(state):
        return with_reply(begin_intake(state["text"], baseline, client), state["text"])

    def clarify(state):
        session = _session(state)
        answer = interrupt(
            {
                "kind": "question",
                "reply": state.get("reply"),
                "questions": _current_questions(session),
                "choices": session.pending[0].choices if session.pending else [],
            }
        )
        updated = answer_intake(session, answer, baseline, client)
        if updated.result.state == "invalid_model_output" and session.pending:
            updated = _retry(session, updated)
        return with_reply(updated, answer)

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
        target_scenario_id = (
            f"{baseline.scenario.scenario_id}_siparis"
            if scenario_id == baseline.scenario.scenario_id
            else scenario_id
        )
        simulation = execute_tool(
            "simulate_order",
            {
                "intake": _session(state).result.model_dump(),
                "scenario_id": target_scenario_id,
            },
            baseline,
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
            return {"inspection": result.inspection, "message": answer.text}
        return {
            "message": " ".join([state.get("reply") or "", *result.questions]).strip()
        }

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

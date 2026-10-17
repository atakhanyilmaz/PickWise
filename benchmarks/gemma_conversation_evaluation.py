"""Real-model evaluation with separate development and heldout fixtures."""

import argparse
import hashlib
import json
from pathlib import Path
from time import perf_counter

from pydantic import Field

from core.domain_rules import Contract
from core.llm.conversation import answer_intake, begin_intake
from core.llm.ollama_client import OllamaClient
from core.scenarios import PlanSnapshot


class Case(Contract):
    id: str
    text: str
    initial_state: str
    final_state: str
    tool: str
    answers: list[str]
    expected_times: list[dict[int, int]]
    deadline: int | None
    due_date: int | None
    preserve_existing_completions: bool = False
    initial_pending_kind: str | None = None


class Fixture(Contract):
    cases: list[Case] = Field(min_length=1)


def evaluate_case(case, baseline, client):
    start = perf_counter()
    initial = begin_intake(case.text, baseline, client)
    session = initial
    applied = 0
    for answer in case.answers:
        if session.result.state != "clarification" or not session.pending:
            break
        session = answer_intake(session, answer, baseline, client)
        applied += 1
    fields_correct = None
    if case.expected_times:
        order = session.result.proposed_order
        fields_correct = bool(
            order
            and [op.processing_times for op in order.operations] == case.expected_times
            and order.deadline == case.deadline
            and order.due_date == case.due_date
            and session.result.preserve_existing_completions
            == case.preserve_existing_completions
        )
    passed = (
        initial.result.state == case.initial_state
        and session.result.state == case.final_state
        and session.result.tool == case.tool
        and applied == len(case.answers)
        and fields_correct is not False
    )
    pending_correct = None
    if case.initial_pending_kind is not None:
        pending_correct = bool(
            initial.pending and initial.pending[0].kind == case.initial_pending_kind
        )
        passed = passed and pending_correct
    model_stages = [
        s
        for s in session.audit
        if "metadata" in s
        and s.get("stage")
        in ("intent", "fields", "operations_followup", "field_answer")
    ]
    return {
        "id": case.id,
        "passed": passed,
        "seconds": perf_counter() - start,
        "initial_state_correct": initial.result.state == case.initial_state,
        "final_state_correct": session.result.state == case.final_state,
        "tool_correct": session.result.tool == case.tool,
        "fields_correct": fields_correct,
        "clarification_field_correct": pending_correct,
        "answers_applied": applied,
        "validated_model_stage_count": len(model_stages),
        "initial": initial.model_dump(mode="json"),
        "final": session.model_dump(mode="json"),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--split", choices=["development", "heldout"], default="development"
    )
    parser.add_argument("--model", default="gemma4:e2b")
    parser.add_argument(
        "--fixture",
        type=Path,
        help="Separate synthetic fixture; never overwrites development/heldout inputs.",
    )
    parser.add_argument(
        "--baseline", type=Path, default=Path("results/workshop_order/baseline.json")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("results/gemma_conversation")
    )
    args = parser.parse_args()
    baseline = PlanSnapshot.model_validate_json(args.baseline.read_text())
    fixture_path = args.fixture or Path(f"data/examples/gemma/{args.split}.json")
    fixture_bytes = fixture_path.read_bytes()
    raw = json.loads(fixture_bytes)
    cases = Fixture.model_validate({"cases": raw}).cases
    if len({case.id for case in cases}) != len(cases):
        raise ValueError("Fixture case IDs must be unique")
    client = OllamaClient(args.model, timeout=45)
    folder = args.output / args.split
    folder.mkdir(parents=True, exist_ok=True)
    records = []
    for case in cases:
        record = evaluate_case(case, baseline, client)
        records.append(record)
        (folder / f"{case.id}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            case.id,
            record["initial"]["result"]["state"],
            "->",
            record["final"]["result"]["state"],
            record["passed"],
            flush=True,
        )
    field_records = [r for r in records if r["fields_correct"] is not None]
    clarification_records = [
        r for r in records if r["clarification_field_correct"] is not None
    ]
    summary = {
        "split": args.split,
        "fixture": str(fixture_path),
        "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
        "cases": len(records),
        "passed": sum(r["passed"] for r in records),
        "initial_state_accuracy": sum(r["initial_state_correct"] for r in records)
        / len(records),
        "final_state_accuracy": sum(r["final_state_correct"] for r in records)
        / len(records),
        "service_tool_accuracy": sum(r["tool_correct"] for r in records) / len(records),
        "final_field_accuracy": sum(r["fields_correct"] for r in field_records)
        / len(field_records)
        if field_records
        else None,
        "validated_model_stage_count": sum(
            r["validated_model_stage_count"] for r in records
        ),
        "clarification_field_accuracy": sum(
            r["clarification_field_correct"] for r in clarification_records
        )
        / len(clarification_records)
        if clarification_records
        else None,
        "invalid_model_output_count": sum(
            r["final"]["result"]["state"] == "invalid_model_output" for r in records
        ),
        "model_unavailable_count": sum(
            r["final"]["result"]["state"] == "model_unavailable" for r in records
        ),
        "total_seconds": sum(r["seconds"] for r in records),
        "scope": "Small synthetic fixture; service includes code guards and scripted user answers. Not raw-model accuracy or real-workshop validation.",
    }
    (folder / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(summary, flush=True)


if __name__ == "__main__":
    main()

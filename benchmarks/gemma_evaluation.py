"""Small real-Gemma smoke evaluation, separate from mocked unit tests."""

import argparse
import json
from pathlib import Path
from time import perf_counter

from core.llm.explanation import explain_simulation
from core.llm.intake import extract_order
from core.llm.ollama_client import OllamaClient
from core.scenarios import PlanSnapshot, OrderRequest, simulate_order
from benchmarks.workshop_order_demo import DemoInput

CASES = [
    (
        "complete",
        "Yeni sipariş: tornalama, Torna 1 üzerinde 10 dakika. Sert termin t=20 dakika.",
        "confirmation_required",
        "simulate_order",
    ),
    (
        "missing_duration",
        "Yeni sipariş: Torna 1 üzerinde tornalama yapacağız.",
        "clarification",
        "simulate_order",
    ),
    (
        "ambiguous_machine",
        "Yeni sipariş: torna üzerinde 10 dakika tornalama.",
        "clarification",
        "simulate_order",
    ),
    (
        "ambiguous_date",
        "Yeni sipariş: Torna 1 üzerinde 10 dakika tornalama, yarın sabah teslim.",
        "unsupported",
        "simulate_order",
    ),
    (
        "inspect",
        "Mevcut planın bitişini ve gecikmelerini göster.",
        "inspection",
        "inspect_plan",
    ),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gemma4:e2b")
    parser.add_argument(
        "--baseline", type=Path, default=Path("results/workshop_order/baseline.json")
    )
    parser.add_argument("--output", type=Path, default=Path("results/gemma_evaluation"))
    args = parser.parse_args()
    client = OllamaClient(args.model)
    baseline = PlanSnapshot.model_validate_json(args.baseline.read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    records = []
    for name, text, expected, tool in CASES:
        start = perf_counter()
        result = extract_order(text, baseline, client)
        passed = result.state == expected and result.tool == tool
        if name == "complete" and result.proposed_order:
            passed &= (
                result.proposed_order.deadline == 20
                and len(result.proposed_order.operations) == 1
                and result.proposed_order.operations[0].processing_times == {100: 10}
            )
        record = {
            "name": name,
            "expected_state": expected,
            "expected_tool": tool,
            "passed": passed,
            "seconds": perf_counter() - start,
            "intake": result.model_dump(mode="json"),
        }
        records.append(record)
        (args.output / f"{name}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(name, result.state, result.tool, passed, flush=True)
    # Explanation uses a known synthetic order, independent of extraction accuracy.
    demo = DemoInput.model_validate_json(
        Path("data/examples/order_demo.json").read_text()
    )
    simulation = simulate_order(
        baseline,
        OrderRequest(
            baseline_version_id=baseline.version_id,
            scenario_id="explanation_evaluation",
            order=demo.new_order,
            allow_demo=True,
        ),
    )
    explanation = explain_simulation(simulation, client)
    (args.output / "explanation.json").write_text(
        explanation.model_dump_json(indent=2), encoding="utf-8"
    )
    summary = {
        "evaluation_type": "real_local_model_smoke",
        "cases": len(records),
        "passed": sum(r["passed"] for r in records),
        "state_accuracy": sum(
            r["intake"]["state"] == r["expected_state"] for r in records
        )
        / len(records),
        "tool_accuracy": sum(r["intake"]["tool"] == r["expected_tool"] for r in records)
        / len(records),
        "full_extraction_correct": records[0]["passed"],
        "explanation_origin": explanation.origin,
        "scope": "Five synthetic requests; not a production-quality evaluation or offline network-disabled test.",
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(summary, flush=True)


if __name__ == "__main__":
    main()

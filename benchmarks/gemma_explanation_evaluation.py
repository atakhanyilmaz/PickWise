"""Real Gemma fact selection on synthetic feasible/infeasible planning results."""

import argparse
import json
from pathlib import Path

from benchmarks.workshop_order_demo import DemoInput
from core.llm.explanation import computed_facts, explain_simulation
from core.llm.ollama_client import OllamaClient
from core.scenarios import OrderRequest, create_snapshot, simulate_order


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gemma4:e2b")
    parser.add_argument(
        "--output", type=Path, default=Path("results/gemma_quality_explanation")
    )
    args = parser.parse_args()
    demo = DemoInput.model_validate_json(
        Path("data/examples/order_demo.json").read_text()
    )
    baseline = create_snapshot(demo.baseline, "explanation_baseline", 2)
    original = baseline.model_dump()
    client = OllamaClient(args.model, timeout=45)
    args.output.mkdir(parents=True, exist_ok=True)
    records = []
    for name, protect, expected_status in [
        ("feasible", False, "OPTIMAL"),
        ("infeasible", True, "INFEASIBLE"),
    ]:
        simulation = simulate_order(
            baseline,
            OrderRequest(
                baseline_version_id=baseline.version_id,
                scenario_id=f"explain_{name}",
                order=demo.new_order,
                preserve_existing_completions=protect,
                allow_demo=True,
                time_limit_seconds=2,
            ),
        )
        explanation = explain_simulation(simulation, client)
        facts = computed_facts(simulation)
        grounded = (
            set(explanation.selected_fact_ids) <= facts.keys()
            and explanation.text
            == "\n".join(facts[key] for key in explanation.selected_fact_ids)
            and baseline.model_dump() == original
        )
        record = {
            "case": name,
            "status": simulation.result.status,
            "expected_status": expected_status,
            "grounded_rendering": grounded,
            "real_model_selection": explanation.origin == "gemma_selected_facts",
            "passed": grounded
            and simulation.result.status == expected_status
            and explanation.origin == "gemma_selected_facts",
            "explanation": explanation.model_dump(mode="json"),
        }
        records.append(record)
        (args.output / f"{name}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2)
        )
        print(name, record["status"], explanation.origin, record["passed"], flush=True)
    summary = {
        "cases": len(records),
        "passed": sum(r["passed"] for r in records),
        "scope": "Synthetic fixtures. Tests real-model fact selection and trusted rendering, not free-form numerical reasoning or workshop validation.",
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2)
    )
    print(summary, flush=True)


if __name__ == "__main__":
    main()

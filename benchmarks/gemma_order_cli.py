"""UI-independent service demo. Manual mode works without Ollama."""

import argparse
import json
from pathlib import Path

from core.domain_rules import JobModel
from core.llm.explanation import explain_inspection, explain_simulation
from core.llm.tools import execute_tool
from core.llm.conversation import begin_intake, answer_intake
from core.llm.ollama_client import OllamaClient
from core.scenarios import OrderRequest, PlanSnapshot, simulate_order


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--text")
    source.add_argument("--order-json", type=Path)
    parser.add_argument("--model", default="gemma4:e2b")
    parser.add_argument(
        "--debug-json",
        action="store_true",
        help="Show full structured model/service output",
    )
    parser.add_argument("--output", type=Path, default=Path("results/gemma_order"))
    args = parser.parse_args()
    baseline = PlanSnapshot.model_validate_json(args.baseline.read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    client = None
    if args.text:
        client = OllamaClient(args.model)
        session = begin_intake(args.text, baseline, client)
        for _ in range(12):
            (args.output / "session.json").write_text(
                session.model_dump_json(indent=2), encoding="utf-8"
            )
            if session.result.state != "clarification" or not session.pending:
                break
            slot = session.pending[0]
            print(slot.question)
            if slot.choices:
                print(
                    "Örnek yanıtlar (kendi cümlenizle de cevaplayabilirsiniz):",
                    ", ".join(slot.choices),
                )
            answer = input("Yanıt (vazgeçmek için iptal): ")
            if answer.strip().lower() == "iptal":
                print("İstek iptal edildi; simülasyon çalıştırılmadı.")
                return
            session = answer_intake(session, answer, baseline, client)
        (args.output / "session.json").write_text(
            session.model_dump_json(indent=2), encoding="utf-8"
        )
        intake = session.result
        (args.output / "intake.json").write_text(
            intake.model_dump_json(indent=2), encoding="utf-8"
        )
        if args.debug_json:
            print(intake.model_dump_json(indent=2))
        if intake.state == "inspection":
            print("Araç: inspect_plan")
            explanation = explain_inspection(
                intake.user_text, intake.inspection, client
            )
            (args.output / "explanation.json").write_text(
                explanation.model_dump_json(indent=2), encoding="utf-8"
            )
            print(explanation.text)
            return
        if intake.state != "confirmation_required":
            print("\n".join(intake.questions))
            return
        print("Araç: simulate_order — önce sipariş taslağı doğrulanacak.")
        print("Sipariş:", intake.proposed_order.name)
        machine_names = {m.machine_id: m.name for m in baseline.scenario.machines}
        for index, operation in enumerate(intake.proposed_order.operations, 1):
            choices = ", ".join(
                f"{machine_names[m]}: {t} dakika"
                for m, t in operation.processing_times.items()
            )
            print(f"{index}. {operation.name}: {choices}")
        print(
            "Sert termin:",
            intake.proposed_order.deadline,
            "Yumuşak termin:",
            intake.proposed_order.due_date,
        )
        print(
            "Mevcut bitişleri koru:",
            "evet" if intake.preserve_existing_completions else "hayır",
        )
        print("Çıkarılan makine, süre, operasyon sırası ve terminleri kontrol edin.")
        if (
            input("Bu sipariş taslağını doğruluyor musunuz? (evet/hayır): ")
            .strip()
            .lower()
            != "evet"
        ):
            print("Simülasyon çalıştırılmadı.")
            return
        simulation = execute_tool(
            "simulate_order",
            {
                "intake": intake.model_dump(),
                "scenario_id": "confirmed_order_simulation",
            },
            baseline,
            user_confirmed=True,
        )
    else:
        order = JobModel.model_validate_json(args.order_json.read_text())
        # A manually prepared input must already carry explicit user approval.
        simulation = simulate_order(
            baseline,
            OrderRequest(
                baseline_version_id=baseline.version_id,
                scenario_id="manual_order_simulation",
                order=order,
            ),
        )
    explanation = explain_simulation(simulation, client)
    (args.output / "simulation.json").write_text(
        simulation.model_dump_json(indent=2), encoding="utf-8"
    )
    (args.output / "explanation.json").write_text(
        explanation.model_dump_json(indent=2), encoding="utf-8"
    )
    print(explanation.text)
    (args.output / "run.json").write_text(
        json.dumps(
            {
                "manual_input": args.order_json is not None,
                "explanation_origin": explanation.origin,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

"""Manual outage simulation or a synthetic before/after demonstration."""

import argparse
import json
from html import escape
from pathlib import Path

import plotly.graph_objects as go

from benchmarks.workshop_order_demo import chart
from core.domain_rules import WorkshopScenario
from core.downtime import DowntimeRequest, simulate_downtime
from core.scenarios import PlanSnapshot, create_snapshot


def downtime_chart(scenario, result, title):
    fig = chart(scenario, result, title)
    for machine in scenario.machines:
        for start, end in machine.unavailable_intervals:
            fig.add_trace(
                go.Bar(
                    name=f"Duruş — {machine.name}",
                    orientation="h",
                    y=[machine.name],
                    x=[end - start],
                    base=[start],
                    marker=dict(color="#6b7280", pattern_shape="/"),
                    hovertemplate="Duruş<br>Başlangıç: %{base}<br>Süre: %{x} dk<extra></extra>",
                )
            )
    return fig


def export(baseline, simulation, directory, note):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "baseline.json").write_text(
        baseline.model_dump_json(indent=2), encoding="utf-8"
    )
    (directory / "simulation.json").write_text(
        simulation.model_dump_json(indent=2), encoding="utf-8"
    )
    sections = [
        '<!doctype html><html lang="tr"><meta charset="utf-8"><title>Makine duruşu</title>',
        "<style>body{font:16px system-ui;max-width:1100px;margin:30px auto;padding:20px}td,th{border:1px solid #ddd;padding:8px}table{border-collapse:collapse}</style>",
        "<h1>Makine duruşunun plana etkisi</h1>",
        f"<p>{escape(note)}</p>",
        "<p>t=0'dan tamsayı dakika; sürekli çalışma, bölünemez operasyonlar. Amaç sert sınırlar altında makespan azaltma.</p>",
        f"<p><strong>{escape(simulation.result.status)}</strong>: {escape(simulation.message)}</p>",
        f"<p>Duruş: M{simulation.request.machine_id}, [{simulation.request.start}, {simulation.request.end}). {escape(simulation.request.reason)}</p>",
        downtime_chart(baseline.scenario, baseline.result, "Önce").to_html(
            full_html=False, include_plotlyjs=True
        ),
    ]
    if simulation.comparison is not None:
        c = simulation.comparison
        sections.extend(
            [
                downtime_chart(simulation.scenario, simulation.result, "Sonra").to_html(
                    full_html=False, include_plotlyjs=False
                ),
                f"<p>Makespan: {c.before.makespan} → {c.after.makespan} dk. Geciken mevcut iş: {c.delayed_existing_job_count}. Toplam termin gecikmesi: {c.after.total_tardiness} dk.</p>",
                "<table><tr><th>İş</th><th>Önce bitiş</th><th>Sonra bitiş</th><th>Fark</th><th>Sonra termin gecikmesi</th></tr>",
            ]
        )
        for impact in c.impacts:
            tardiness = (
                impact.after_tardiness
                if impact.after_tardiness is not None
                else "Termin yok"
            )
            sections.append(
                f"<tr><td>{escape(impact.name)}</td><td>{impact.before_completion}</td><td>{impact.after_completion}</td><td>{impact.completion_delta}</td><td>{tardiness}</td></tr>"
            )
        sections.append("</table>")
    sections.append(
        "<p>Simülasyon başlangıç planını veya SQLite güncel sürümünü değiştirmez. Kaydetmek ayrı insan seçimi ve yeni plan sürümü gerektirir.</p></html>"
    )
    (directory / "report.html").write_text("\n".join(sections), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--request", type=Path)
    parser.add_argument(
        "--output", type=Path, default=Path("results/workshop_downtime")
    )
    args = parser.parse_args()
    if bool(args.baseline) != bool(args.request):
        parser.error("--baseline ve --request birlikte verilmelidir")
    if args.baseline:
        baseline = PlanSnapshot.model_validate_json(
            args.baseline.read_text(encoding="utf-8")
        )
        request = DowntimeRequest.model_validate_json(
            args.request.read_text(encoding="utf-8")
        )
        result = simulate_downtime(baseline, request)
        export(
            baseline,
            result,
            args.output,
            "Kullanıcı tarafından sağlanan plan ve duruş isteği.",
        )
        print(result.message)
        return
    demo = json.loads(Path("data/examples/order_demo.json").read_text(encoding="utf-8"))
    baseline = create_snapshot(
        WorkshopScenario.model_validate(demo["baseline"]), "downtime-demo-v1", 2
    )
    for name, changes in [
        ("delay", {}),
        ("boundary", {"start": 15}),
        ("protected", {"preserve_existing_completions": True}),
        ("alternative", {}),
    ]:
        base = baseline
        if name == "alternative":
            data = baseline.scenario.model_dump()
            data["jobs"][1]["operations"][0]["processing_times"][200] = 7
            base = create_snapshot(
                WorkshopScenario.model_validate(data), "downtime-demo-alt-v1", 2
            )
        request = DowntimeRequest.model_validate(
            {
                "baseline_version_id": base.version_id,
                "scenario_id": f"outage-{name}",
                "machine_id": 100,
                "start": 10,
                "end": 20,
                "reason": "Sentetik planlı bakım",
                "time_limit_seconds": 2,
            }
            | changes
        )
        result = simulate_downtime(base, request)
        export(
            base,
            result,
            args.output / name,
            "Sentetik demo: süreler, terminler ve makine uygunluğu varsayımdır.",
        )
        print(f"{name}: {result.result.status}, makespan={result.result.makespan}")


if __name__ == "__main__":
    main()

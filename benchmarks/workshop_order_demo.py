"""Run the synthetic new-order demonstration and export an offline HTML report."""

import argparse
import csv
from html import escape
from pathlib import Path

import plotly.graph_objects as go

from core.domain_rules import Contract, JobModel, WorkshopScenario
from core.scenarios import OrderRequest, create_snapshot, simulate_order


class DemoInput(Contract):
    baseline: WorkshopScenario
    new_order: JobModel
    alternative_order: JobModel


def chart(scenario, result, title):
    fig = go.Figure()
    for j, job in enumerate(scenario.jobs):
        rows = [r for r in result.schedule if r.source_job_id == job.job_id]
        machines = {m.machine_id: m.name for m in scenario.machines}
        fig.add_trace(
            go.Bar(
                name=job.name,
                orientation="h",
                y=[machines[r.source_machine_id] for r in rows],
                x=[r.end - r.start for r in rows],
                base=[r.start for r in rows],
                text=[f"{job.name} / O{r.source_operation_id}" for r in rows],
                marker_color=["#2563eb", "#d97706", "#059669"][j % 3],
                hovertemplate="%{text}<br>Başlangıç: %{base}<br>Süre: %{x} dk<extra></extra>",
            )
        )
    fig.add_vline(x=scenario.current_time, line_dash="dash", annotation_text="Şimdi")
    fig.update_layout(
        title=title,
        barmode="overlay",
        xaxis_title="t=0 referansından dakika",
        yaxis_title="Makine",
        height=350,
        legend=dict(orientation="h"),
    )
    return fig


def export_report(baseline, simulations, output):
    output.mkdir(parents=True, exist_ok=True)
    (output / "baseline.json").write_text(
        baseline.model_dump_json(indent=2), encoding="utf-8"
    )
    sections = [
        '<!doctype html><html lang="tr"><meta charset="utf-8"><title>Sipariş senaryoları</title>',
        "<style>body{font:16px system-ui;margin:32px auto;max-width:1100px;padding:0 20px;color:#172033}table{border-collapse:collapse;width:100%;margin:20px 0}td,th{border:1px solid #ccd3df;padding:9px;text-align:left}h1,h2{color:#174379}</style>",
        "<h1>Yeni siparişin plana etkisi</h1><p><strong>Sentetik demo:</strong> süreler, terminler ve alternatif makine uygunluğu demo varsayımıdır. Sürekli çalışma; operasyonlar bölünemez. Amaç sert sınırlar altında makespan azaltmadır. Yumuşak termin gecikmeleri raporlanır.</p>",
        chart(baseline.scenario, baseline.result, "Önce — başlangıç planı").to_html(
            full_html=False, include_plotlyjs=True
        ),
    ]
    summary = []
    for name, simulation in simulations.items():
        (output / f"{name}.json").write_text(
            simulation.model_dump_json(indent=2), encoding="utf-8"
        )
        sections += [f"<h2>{escape(name)}</h2><p>{escape(simulation.message)}</p>"]
        record = {
            "scenario": name,
            "status": simulation.result.status,
            "makespan": simulation.result.makespan,
            "runtime_seconds": simulation.result.runtime_seconds,
            "violation_count": len(simulation.result.violations)
            if simulation.result.violations is not None
            else None,
            "delayed_existing_jobs": None,
            "late_jobs": None,
            "total_tardiness": None,
            "new_order_completion": None,
        }
        if simulation.comparison:
            c = simulation.comparison
            new_job = next(j for j in c.after.jobs if j.job_id in c.new_job_ids)
            record.update(
                delayed_existing_jobs=c.delayed_existing_job_count,
                late_jobs=c.after.late_job_count,
                total_tardiness=c.after.total_tardiness,
                new_order_completion=new_job.completion,
            )
            sections += [
                f"<p>Yeni sipariş bitişi: <b>{new_job.completion} dk</b>. Makespan: {c.before.makespan} → {c.after.makespan} dk. Mevcut plandan geç biten iş: {c.delayed_existing_job_count}. Terminini aşan iş: {c.after.late_job_count}. Toplam termin gecikmesi: {c.after.total_tardiness} dk.</p>",
                chart(
                    simulation.scenario, simulation.result, "Sonra — " + name
                ).to_html(full_html=False, include_plotlyjs=False),
                "<table><tr><th>Mevcut iş</th><th>Önce bitiş</th><th>Sonra bitiş</th><th>Fark (dk)</th><th>Önce termin gecikmesi</th><th>Sonra termin gecikmesi</th></tr>",
            ]
            for impact in c.impacts:
                sections.append(
                    f"<tr><td>{escape(impact.name)}</td><td>{impact.before_completion}</td><td>{impact.after_completion}</td><td>{impact.completion_delta:+d}</td><td>{impact.before_tardiness if impact.before_tardiness is not None else 'Terminsiz'}</td><td>{impact.after_tardiness if impact.after_tardiness is not None else 'Terminsiz'}</td></tr>"
                )
            sections.append("</table>")
        else:
            sections.append(
                "<p>Karşılaştırılabilir yeni çizelge üretilmedi. Başlangıç planı korunur.</p>"
            )
        summary.append(record)
    sections.append(
        "<p>Bu rapor senaryo çıktısıdır. Onaylı üretim planını değiştirmez.</p></html>"
    )
    (output / "comparison.html").write_text("\n".join(sections), encoding="utf-8")
    with (output / "summary.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=summary[0].keys())
        writer.writeheader()
        writer.writerows(summary)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input", type=Path, default=Path("data/examples/order_demo.json")
    )
    parser.add_argument("--output", type=Path, default=Path("results/workshop_order"))
    parser.add_argument("--time-limit", type=float, default=10)
    args = parser.parse_args()
    demo = DemoInput.model_validate_json(args.input.read_text(encoding="utf-8"))
    baseline = create_snapshot(demo.baseline, "demo_baseline_v1", args.time_limit)
    simulations = {}
    for name, order, protect in [
        ("Tek makine", demo.new_order, False),
        ("Alternatif makine", demo.alternative_order, False),
        ("Mevcut bitişleri koru", demo.new_order, True),
    ]:
        simulation = simulate_order(
            baseline,
            OrderRequest(
                baseline_version_id=baseline.version_id,
                scenario_id=f"{demo.baseline.scenario_id}_{len(simulations) + 1}",
                order=order,
                preserve_existing_completions=protect,
                allow_demo=True,
                time_limit_seconds=args.time_limit,
            ),
        )
        simulations[name] = simulation
        print(name, simulation.result.status, simulation.result.makespan, flush=True)
    export_report(baseline, simulations, args.output)
    print(args.output / "comparison.html")


if __name__ == "__main__":
    main()

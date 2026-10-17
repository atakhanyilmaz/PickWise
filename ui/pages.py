"""Streamlit pages (WP-1N, WP-2N). Each page only loads data through existing services and composes ui.components."""

import json
import sqlite3
from collections import defaultdict
from pathlib import Path

import pandas as pd
import streamlit as st

from benchmarks.workshop_order_demo import DemoInput
from core.cpsat_solver import COMMIT, UPSTREAM, read_instance, solve
from core.pipeline import dispatch
from core.scenarios import create_snapshot, plan_metrics
from core.sqlite_repository import PlanStorageError, SQLitePlanRepository
from core.validation import validate
from ui import components as ui

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "database/local/workshop.sqlite3"
PLAN_ID = "synthetic-workshop"
RESULTS = ROOT / "results/brandimarte"
INSTANCES = [f"Mk{i:02}" for i in range(1, 11)]
METHODS = {"cp_sat": "CP-SAT", "job_order_eft": "Referans"}
EXPERIMENT = ROOT / "experiments/tabpfn/results/regressor_comparison"
# label -> (task key, display unit, minutes per unit)
TASKS = {
    "Toplam iş süresi": ("total_case_span", "gün", 1440),
    "Makineler arası bekleme": ("conditional_machine_gap", "saat", 60),
}
MODELS = {
    "global_median": "Global medyan",
    "group_median": "Grup medyanı",
    "quantile_linear": "Medyan regresyonu",
    "gradient_boosting_mae": "Gradient Boosting",
    "catboost_mae": "CatBoost",
    "tabpfn_v2": "TabPFN v2",
    "extra_trees": "ExtraTrees",
}
FEATURES = {
    "part": "parça",
    "quantity": "miktar",
    "from": "önceki makine",
    "to": "sonraki makine",
}


@st.cache_resource
def demo_snapshot():
    demo = DemoInput.model_validate_json(
        (ROOT / "data/examples/order_demo.json").read_text(encoding="utf-8")
    )
    return create_snapshot(demo.baseline, "demo_baseline_v1", time_limit=10)


def current_plan():
    """(snapshot, label, saved): latest approved plan from SQLite, else the unsaved demo baseline."""
    if DB.exists():
        try:
            record = SQLitePlanRepository(DB).load_current(PLAN_ID)
            label = f"{record.snapshot.version_id} · onaylayan {record.approved_by}"
            return record.snapshot, label, True
        except (KeyError, PlanStorageError, sqlite3.Error):
            pass
    return demo_snapshot(), "Demo planı · kaydedilmemiş", False


def utilization(rows, machines, makespan):
    busy = defaultdict(int)
    for r in rows:
        busy[r["machine"]] += r["end"] - r["start"]
    shares = {name: busy[i] / makespan for i, name in enumerate(machines)}
    busiest = max(shares, key=shares.get)
    return sum(shares.values()) / len(shares), busiest, shares[busiest]


def plan_page():
    snapshot, source, _ = current_plan()
    scenario, result = snapshot.scenario, snapshot.result
    metrics = plan_metrics(scenario, result)
    rows = [row.model_dump() for row in result.schedule]
    machines = [m.name for m in scenario.machines]
    average, busiest, peak = utilization(rows, machines, metrics.makespan)

    st.title("Plan")
    st.caption(
        f"Etkin plan: {source} · {len(scenario.jobs)} iş · {len(machines)} tezgâh · "
        f"şu an {ui.clock(scenario.current_time)}"
    )
    ui.metric_row(
        [
            (
                "Tüm işler biter",
                ui.clock(metrics.makespan)[-5:],
                f"makespan {metrics.makespan} dk",
            ),
            (
                "Ortalama tezgâh doluluğu",
                f"%{average * 100:.0f}",
                f"en yoğun: {busiest} %{peak * 100:.0f}",
            ),
            (
                "Doğrulama",
                "Hatasız"
                if metrics.violation_count == 0
                else f"{metrics.violation_count} ihlal",
                "çakışma ve sıra ihlali denetlendi",
            ),
            ("Çözücü durumu", *ui.status_metric(result.status)),
        ]
    )

    st.subheader("Şu an tezgâhlarda")
    minute = st.slider(
        "Görüntülenen an (t=0'dan dakika)",
        0,
        max(metrics.makespan, scenario.current_time),
        scenario.current_time,
        help="Varsayılan: planın şimdiki anı. Kaydırarak gün içindeki başka bir anı görün.",
    )
    st.caption(f"{ui.clock(minute)} itibarıyla")
    ui.dispatch_board(dispatch(scenario, result, minute))

    st.subheader("Tezgâh yükleme")
    ui.gantt(
        rows,
        machines=machines,
        job_label=lambda j: scenario.jobs[j].name,
        x_title="t=0 referansından dakika",
    )
    st.caption(scenario.description or scenario.time_unit_note)

    st.subheader("Siparişler")
    by_job = {m.job_id: m for m in metrics.jobs}
    starts = defaultdict(list)
    for r in rows:
        starts[r["job"]].append(r["start"])
    ui.table(
        [
            {
                "Sipariş": job.name,
                "Rota": " → ".join(op.name for op in job.operations),
                "Başlangıç": ui.clock(min(starts[j])),
                "Bitiş": ui.clock(by_job[job.job_id].completion),
                "Termin": ui.clock(job.due_date),
                "Gecikme (dk)": by_job[job.job_id].tardiness,
                "Rota kaynağı": [ui.SOURCE_LABELS[job.route_source]],
                "Süre kaynağı": sorted(
                    {ui.SOURCE_LABELS[op.duration_source] for op in job.operations}
                ),
            }
            for j, job in enumerate(scenario.jobs)
        ],
        column_config={
            "Rota": st.column_config.TextColumn(width="medium"),
            **{
                column: st.column_config.TextColumn(width="small")
                for column in ("Başlangıç", "Bitiş", "Termin")
            },
            "Gecikme (dk)": st.column_config.NumberColumn(width="small"),
            "Rota kaynağı": ui.source_column("Rota kaynağı"),
            "Süre kaynağı": ui.source_column("Süre kaynağı"),
        },
    )


@st.cache_resource
def demo_drafts():
    demo = DemoInput.model_validate_json(
        (ROOT / "data/examples/order_demo.json").read_text(encoding="utf-8")
    )
    return {
        "Demo sipariş": demo.new_order,
        "Alternatif tezgâhlı demo": demo.alternative_order,
        "Boş rota": None,
    }


def route_page():
    snapshot, _, _ = current_plan()
    machines = snapshot.scenario.machines
    drafts = demo_drafts()

    st.title("Rota onayı")
    st.caption(
        "Siparişin işlem sırasını, uygun tezgâhları ve sürelerini kontrol edin. "
        "Onaylanmamış rota çözücüye girmez."
    )

    choice = st.segmented_control(
        "Taslak", list(drafts), default="Demo sipariş", required=True
    )
    base = drafts[choice]
    name_column, source_column = st.columns([3, 1], vertical_alignment="bottom")
    name = name_column.text_input("Sipariş adı", base.name if base else "")
    badge_slot = source_column.empty()  # filled once the route's final state is known

    def show_route_source(source):
        with badge_slot.container():
            st.caption("Rota kaynağı")
            ui.source_badge(source)

    if base and base.route_source == "retrospective":
        st.warning(
            "Bu rota geçmiş kayıtlardan çıkarıldı. Planlamaya girmeden önce işlem sırasını, "
            "tezgâhları ve süreleri kontrol edip onaylayın.",
            icon=":material/history:",
        )

    st.subheader("İşlem sırası ve süreler")
    st.caption(
        "Satır sırası işlem sırasıdır. Boş (None) hücre, tezgâhın bu işlemi yapamadığı anlamına gelir. "
        'Süreler dakikadır; düzenlediğiniz süre "Kullanıcı süresi" olur.'
    )
    frame = ui.route_editor(base, machines, key=f"route-{choice}")
    job_id = base.job_id if base else max(j.job_id for j in snapshot.scenario.jobs) + 10
    job, problems = ui.job_from_route(
        frame, name=name, base=base, machines=machines, job_id=job_id
    )

    if problems:
        show_route_source(base.route_source if base else "user_proposed")
        for problem in problems:
            st.warning(problem, icon=":material/edit_note:")
        return

    st.subheader("Süre kaynakları")
    for index, op in enumerate(job.operations, start=1):
        label, badge = st.columns([3, 2], vertical_alignment="center")
        times = " · ".join(
            f"{m.name} {op.processing_times[m.machine_id]} dk"
            for m in machines
            if m.machine_id in op.processing_times
        )
        label.markdown(f"**{index}. {op.name}**  \n{times}")
        with badge:
            ui.source_badge(op.duration_source)

    st.divider()
    approved = st.session_state.get("approved_order")
    is_approved = approved is not None and approved.model_dump(
        exclude={"route_source"}
    ) == job.model_dump(exclude={"route_source"})
    show_route_source(approved.route_source if is_approved else job.route_source)
    if is_approved:
        st.success(
            f"{approved.name} rotası onaylandı. Yeni sipariş simülasyonu bu rotayı kullanacak.",
            icon=":material/verified:",
        )
        return
    confirmed = st.checkbox("İşlem sırasını, tezgâhları ve süreleri kontrol ettim")
    if st.button("Rotayı onayla", type="primary", disabled=not confirmed):
        st.session_state["approved_order"] = ui.approve(job)
        st.rerun()


@st.cache_data
def solve_instance(name, time_limit):
    env, jobs, machines = read_instance(UPSTREAM / f"data/fjsp/brandimarte/{name}.fjs")
    result = solve(env, time_limit=time_limit)
    result["violations"] = (
        validate(jobs, machines, result["schedule"]) if result["schedule"] else None
    )
    return result


def benchmark_page():
    st.title("Benchmark")
    st.caption(
        "Brandimarte örneklerinde referans yöntem ve CP-SAT karşılaştırması · süreler birimsizdir"
    )

    left, right = st.columns([3, 1], vertical_alignment="bottom")
    name = left.selectbox("Örnek", INSTANCES)
    rerun = right.button(
        f"Yeniden çöz ({st.session_state['time_limit']} sn)", width="stretch"
    )
    path = RESULTS / f"{name}.json"
    if not path.exists():
        st.info(
            "Bu örnek için kayıtlı sonuç yok: `python -m benchmarks.brandimarte_runner --time-limit 10`"
        )
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    cp, ref = data["cp_sat"], data["job_order_eft"]
    if rerun:
        cp = solve_instance(name, float(st.session_state["time_limit"]))
        st.caption(
            f"CP-SAT bu bilgisayarda şimdi {cp['runtime_seconds']:.1f} sn çalıştı."
        )

    gain = (ref["makespan"] - cp["makespan"]) / ref["makespan"] if cp["makespan"] else 0
    ui.metric_row(
        [
            (
                "Örnek boyutu",
                f"{data['jobs']} · {data['machines']} · {data['operations']}",
                "iş · makine · operasyon (dosyadan)",
            ),
            ("CP-SAT makespan", cp["makespan"], ui.status_metric(cp["status"])[1]),
            (
                "Referans makespan",
                ref["makespan"],
                f"CP-SAT %{gain * 100:.0f} daha kısa",
            ),
            (
                "Doğrulama",
                "Hatasız"
                if cp["violations"] == [] and ref["violations"] == []
                else "İhlal var",
                "iki çizelge de bağımsız denetlendi",
            ),
        ]
    )

    method = st.radio("Çizelge", ["CP-SAT", "Referans yöntem"], horizontal=True)
    ui.gantt(
        (cp if method == "CP-SAT" else ref)["schedule"],
        machines=[f"M{i + 1}" for i in range(data["machines"])],
        job_label=lambda j: f"İş {j + 1}",
        x_title="Benchmark zaman birimi",
    )

    summary = pd.read_csv(RESULTS / "summary.csv").rename(
        columns={
            "instance": "Örnek",
            "method": "Yöntem",
            "jobs": "İş",
            "machines": "Makine",
            "operations": "Operasyon",
            "status": "Durum",
            "makespan": "Makespan",
            "best_bound": "Alt sınır",
            "runtime_seconds": "Süre (sn)",
            "violations": "İhlal",
        }
    )
    summary["Yöntem"] = summary["Yöntem"].map(METHODS)
    st.subheader("Makespan karşılaştırması")
    st.caption("Kısa olan daha iyi.")
    st.bar_chart(summary, x="Örnek", y="Makespan", color="Yöntem", stack=False)

    st.subheader("Tüm sonuçlar")
    st.dataframe(summary, hide_index=True, width="stretch")
    meta = data["metadata"]
    st.caption(
        f"Kayıtlı sonuç: {meta['created_utc'][:10]} · OR-Tools {meta['ortools']} · "
        f"{meta['time_limit_seconds']:.0f} sn sınır, tek worker, seed 0. "
        '"Uygulanabilir" sonuç optimal diye etiketlenmez. Referans yöntem kaynak deponun FIFO/SPT uygulaması değildir.'
    )


@st.cache_data
def experiment_report():
    return json.loads(
        (EXPERIMENT / "validation_report.json").read_text(encoding="utf-8")
    )


def experiment_page():
    st.title("Süre tahmini deneyi")
    st.caption(
        "Gerçek Production Analysis verisinde doğrulama sonuçları · keşifsel; "
        "final test skoru hesaplanmadı"
    )
    st.info(
        "Hiçbir model global medyanı güvenilir biçimde geçemedi. Tahmin modelleri "
        "planlamaya bağlanmadı; planlama kullanıcının onayladığı süreleri kullanır.",
        icon=":material/info:",
    )

    label = st.segmented_control(
        "Tahmin edilen süre", list(TASKS), default="Toplam iş süresi", required=True
    )
    key, unit, per_unit = TASKS[label]
    task = experiment_report()["tasks"][key]
    # The gap task weights every case equally, matching the team's main metric.
    metric = "case_macro_mae_minutes"
    scores = pd.DataFrame(
        [
            {
                "Model": MODELS[name],
                "MAE": values[metric] / per_unit,
                "RMSE": values["rmse_minutes"] / per_unit,
                "En büyük hata": values["max_absolute_error_minutes"] / per_unit,
            }
            for name, values in task["validation_scores"].items()
        ]
    ).sort_values("MAE")
    mae = scores.set_index("Model")["MAE"]
    best = mae.idxmin()
    median = mae["Global medyan"]

    def amount(value, sign=False):
        return f"{value:{'+' if sign else ''}.2f} {unit}".replace(".", ",")

    ui.metric_row(
        [
            (
                "Eğitim / doğrulama",
                f"{task['train_cases']} / {task['validation_cases']} iş",
                f"{task['train_rows']} / {task['validation_rows']} satır",
            ),
            (
                "En düşük hata",
                amount(mae[best]),
                best
                if best == "Global medyan"
                else f"{best}: medyandan yalnız {amount(median - mae[best])} iyi; anlamlı kazanım değil",
            ),
            ("Global medyan", amount(median), "karşılaştırma ölçütü"),
            (
                "TabPFN v2",
                amount(mae["TabPFN v2"]),
                f"medyandan {amount(mae['TabPFN v2'] - median, sign=True)}",
            ),
        ]
    )

    st.subheader("Model hataları")
    ui.model_error_chart(scores, "MAE", unit, highlight="Global medyan")
    st.caption(
        "Girdiler: "
        + ", ".join(FEATURES[f] for f in task["features"])
        + ". Turuncu çubuk karşılaştırma ölçütü olan global medyandır."
    )

    st.subheader("Gerçek ve tahmin")
    model = st.selectbox(
        "Model", list(MODELS.values()), index=list(MODELS).index("tabpfn_v2")
    )
    column = next(name for name, title in MODELS.items() if title == model)
    rows = pd.read_csv(EXPERIMENT / f"{key}_validation_predictions.csv")
    ui.prediction_scatter(
        pd.DataFrame(
            {
                "İş": rows["case"],
                "Parça": rows["part"],
                "Gerçek": rows["y"] / per_unit,
                "Tahmin": rows[column] / per_unit,
            }
        ),
        unit,
    )
    st.caption(
        "Kesikli çizgi kusursuz tahmindir; noktalar çizgiden uzaklaştıkça hata büyür."
    )

    st.subheader("Bütün metrikler")
    ui.table(scores.round(2))

    st.subheader("Planlamada süre kaynağı")
    ui.source_badge("user_input")
    st.caption(
        "Varsayılan ve şu anki tek kaynak kullanıcının onayladığı süredir. Bir model "
        "aynı doğrulamada medyanı açıkça geçmedikçe tahmin seçeneği açılmaz."
    )


def about_page():
    st.title("Hakkında")
    st.write(
        "PickWise, fason imalat atölyeleri için bir üretim planlama yardımcısıdır. "
        "Mevcut plana yeni bir sipariş eklendiğinde işlerin ne zaman biteceğini, "
        "hangi tezgâhın yükleneceğini ve hangi siparişlerin etkileneceğini gösterir."
    )
    st.subheader("Bileşenler")
    ui.table(
        [
            {"Bileşen": b, "Ne yapar": w, "Kaynak": k, "Durum": d}
            for b, w, k, d in [
                (
                    "Çizelgeleme ortamı",
                    "İş, operasyon, makine modeli; benchmark ayrıştırıcıları",
                    "Açık kaynak",
                    "Kullanılıyor",
                ),
                (
                    "CP-SAT çözücü",
                    "Makine ataması ve zamanlama",
                    "Açık kaynak + OR-Tools",
                    "Kullanılıyor",
                ),
                (
                    "Doğrulayıcı",
                    "Çizelgeyi çözücüden bağımsız denetler",
                    "Ekip",
                    "Kullanılıyor",
                ),
                (
                    "Atölye modeli",
                    "Termin, duruş, tamamlanmış ve devam eden işlemler",
                    "Ekip",
                    "Kullanılıyor",
                ),
                (
                    "Plan karşılaştırma",
                    "Yeni sipariş öncesi ve sonrası",
                    "Ekip",
                    "Hazır, arayüze bağlanacak",
                ),
                (
                    "Plan sürümleri",
                    "Onaylı planlar (SQLite)",
                    "Ekip",
                    "Plan ekranı okuyor",
                ),
                ("Arayüz", "Streamlit sayfaları ve Gantt", "Ekip", "Bu ekran"),
                ("TabPFN", "Geçmiş kayıtlardan süre tahmini", "Ekip", "Aşama 3"),
                ("EmbeddingGemma", "Benzer geçmiş işleri bulur", "Ekip", "Aşama 5"),
                (
                    "Gemma",
                    "Türkçe talebi forma çevirir, sonucu açıklar",
                    "Ekip",
                    "Deneysel servis hazır",
                ),
            ]
        ]
    )
    left, right = st.columns(2)
    with left:
        st.subheader("Açık kaynak")
        st.write(
            "Çizelgeleme ortamı, Brandimarte verileri ve CP-SAT modeli "
            "[TU Eindhoven Job Shop Scheduling Benchmark](https://github.com/ai-for-decision-making-tue/"
            f"Job_Shop_Scheduling_Benchmark_Environments_and_Instances) deposundan alınmıştır "
            f"(commit {COMMIT[:7]}, MIT lisansı)."
        )
    with right:
        st.subheader("Ekip")
        st.markdown(
            "- **Atakan Yılmaz:** çözücü, dinamik yeniden çizelgeleme, TabPFN, Gemma\n"
            "- **Yunus:** veri hattı, SQLite şeması, EmbeddingGemma\n"
            "- **Nazlısu Başak:** arayüz, Gantt ve görselleştirme, tutorial'lar"
        )
    st.caption(
        "Sürüm 0.1 (demo) · TabPFN ve Gemma model lisansları ayrıca doğrulanacak."
    )

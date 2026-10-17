"""Streamlit pages (WP-1N, WP-2N, WP-4N, WP-5N). Each page only loads data through existing services and composes ui.components."""

import json
import sqlite3
from collections import defaultdict
from datetime import datetime
from importlib import metadata
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from benchmarks.workshop_order_demo import DemoInput
from core import retrospective_transform as production
from core.cpsat_solver import COMMIT, UPSTREAM, read_instance, solve
from core.downtime import DowntimeRequest
from core.pipeline import PipelineRequest, dispatch, run
from core.plan_contract import PlanVersionConflict, StoredPlanVersion
from core.scenarios import OrderRequest, PlanSnapshot, create_snapshot, plan_metrics
from core.sqlite_repository import PlanStorageError, SQLitePlanRepository
from core.validation import validate
from ui import components as ui

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "database/local/workshop.sqlite3"
PLAN_ID = "synthetic-workshop"
RESULTS = ROOT / "results/brandimarte"
INSTANCES = [f"Mk{i:02}" for i in range(1, 11)]
METHODS = {"cp_sat": "CP-SAT", "job_order_eft": "Referans"}


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
                ui.short_clock(metrics.makespan),
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
    }


@st.cache_resource(show_spinner=False)
def production_drafts(version_id, _scenario):
    """Next recorded work orders that run only on this plan version's machines."""
    return {job.name: job for job in production.order_drafts(_scenario)}


def order_drafts(snapshot):
    """Order drafts that fit the active plan's machines; the first is the quick demo order."""
    if snapshot.scenario.scenario_id.startswith(production.SCENARIO_ID):
        drafts = production_drafts(snapshot.version_id, snapshot.scenario)
    else:
        drafts = demo_drafts()
    return drafts | {"Boş rota": None}


def route_page():
    snapshot, _, _ = current_plan()
    machines = snapshot.scenario.machines
    drafts = order_drafts(snapshot)

    st.title("Rota onayı")
    st.caption(
        "Siparişin işlem sırasını, uygun tezgâhları ve sürelerini kontrol edin. "
        "Onaylanmamış rota çözücüye girmez."
    )

    choice = st.segmented_control(
        "Taslak", list(drafts), default=next(iter(drafts)), required=True
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


# The services raise English messages; the UI shows the user what to change.
SERVICE_ERRORS = {
    "intersects a started operation": "Duruş, başlamış bir işlemle çakışıyor; başlamış işlem bölünemez. Duruşu bu işlem bittikten sonraya alın.",
    "cannot rewrite the past": "Duruş, planın şimdiki anından önce başlayamaz.",
    "already exists": "Bu sipariş kimliği planda zaten var.",
}


def explain_error(error):
    text = str(error)
    return next((tr for en, tr in SERVICE_ERRORS.items() if en in text), text)


def save_plan(simulation, parent_version_id, approved_by, path=None):
    """Store a simulated plan as the new approved version; returns its version id.

    parent_version_id is the saved plan the simulation started from (None for the
    unsaved demo). The repository rejects the save if the current version moved meanwhile.
    """
    now = datetime.now(ZoneInfo("Europe/Istanbul"))
    repository = SQLitePlanRepository(path or DB)  # read DB at call time
    repository.initialize()
    version_id = f"v-{now:%Y%m%d-%H%M%S}"
    record = StoredPlanVersion(
        plan_id=PLAN_ID,
        parent_version_id=parent_version_id,
        approved_by=approved_by,
        approved_at=now,
        snapshot=PlanSnapshot(
            version_id=version_id,
            scenario=simulation.scenario,
            result=simulation.result,
        ),
    )
    repository.save_approved_version(
        record, expected_current_version_id=parent_version_id
    )
    return version_id


def order_request(baseline, job, *, due, hard, preserve, demo):
    taken = {j.job_id for j in baseline.scenario.jobs}
    job = job.model_copy(
        update={
            "job_id": job.job_id if job.job_id not in taken else max(taken) + 10,
            "due_date": due,
            "deadline": due if hard else None,
        },
        deep=True,
    )
    return OrderRequest(
        baseline_version_id=baseline.version_id,
        scenario_id=f"{baseline.scenario.scenario_id}-siparis",
        order=job,
        preserve_existing_completions=preserve,
        allow_demo=demo,
        time_limit_seconds=st.session_state["time_limit"],
    )


def change_form(baseline):
    """Order or downtime inputs; returns a PipelineRequest on submit, else None."""
    scenario = baseline.scenario
    kind = st.segmented_control(
        "Değişiklik",
        ["Yeni sipariş", "Makine duruşu"],
        default="Yeni sipariş",
        required=True,
    )
    approved = st.session_state.get("approved_order")
    if kind == "Yeni sipariş" and approved is None:
        st.caption(
            ":material/info: Onaylı rota yok. Rota onayı sayfasında bir rota onaylayın "
            "ya da etiketli demo siparişle deneyin."
        )
    with st.form("change"):
        if kind == "Yeni sipariş":
            sources = (["Onaylı rota"] if approved else []) + ["Demo sipariş"]
            source = st.radio("Sipariş", sources, horizontal=True)
            job = (
                approved
                if source == "Onaylı rota"
                else next(iter(order_drafts(baseline).values()))
            )
            st.markdown(
                f"**{job.name}** · " + " → ".join(op.name for op in job.operations)
            )
            ui.source_badge(job.route_source)
            with_due = st.checkbox("Termin ekle", value=job.due_date is not None)
            due = ui.clock_input(
                "Termin", job.due_date or scenario.current_time + 60, key="due"
            )
            hard = st.checkbox(
                "Sert termin",
                value=job.deadline is not None,
                help="Sert terminde çözücü bu saati aşan planı kabul etmez; "
                "aksi hâlde gecikme yalnız raporlanır.",
            )
        else:
            machine = st.selectbox(
                "Tezgâh", scenario.machines, format_func=lambda m: m.name
            )
            start = ui.clock_input(
                "Duruş başlangıcı", scenario.current_time, key="stop-start"
            )
            end = ui.clock_input(
                "Duruş bitişi", scenario.current_time + 60, key="stop-end"
            )
            reason = st.text_input("Sebep", placeholder="Planlı bakım")
        preserve = st.checkbox(
            "Mevcut işlerin bitiş saatlerini koru",
            help="İşaretlenirse hiçbir mevcut iş önceki planından daha geç bitemez.",
        )
        if not st.form_submit_button("Simüle et", type="primary"):
            return None

    if kind == "Yeni sipariş":
        if with_due and due < scenario.current_time:
            st.error("Termin, planın şimdiki anından önce olamaz.")
            return None
        return PipelineRequest(
            order=order_request(
                baseline,
                job,
                due=due if with_due else None,
                hard=with_due and hard,
                preserve=preserve,
                demo=source == "Demo sipariş",
            )
        )
    if end <= start:
        st.error("Duruş bitişi başlangıcından sonra olmalı.")
        return None
    return PipelineRequest(
        downtime=DowntimeRequest(
            baseline_version_id=baseline.version_id,
            scenario_id=f"{scenario.scenario_id}-durus",
            machine_id=machine.machine_id,
            start=start,
            end=end,
            reason=reason.strip(),
            preserve_existing_completions=preserve,
            time_limit_seconds=st.session_state["time_limit"],
        )
    )


def downtime_bands(scenario):
    return [
        (m.name, start, end)
        for m in scenario.machines
        for start, end in m.unavailable_intervals
    ]


def simulation_result(baseline, outcome, parent_version_id, state_key="simulation"):
    """Before/after view and the save panel; `state_key` is the session entry cleared after saving."""
    simulation = outcome.simulation
    if simulation.comparison is None:
        st.error(
            f"{simulation.message} Başlangıç planı korunur; kaydedilecek yeni plan yok.",
            icon=":material/block:",
        )
        return
    st.success(simulation.message, icon=":material/check_circle:")
    comparison = simulation.comparison
    ui.comparison_metrics(comparison)
    for job in comparison.after.jobs:
        if job.job_id in comparison.new_job_ids:
            late = f", {job.tardiness} dk gecikme" if job.tardiness else ""
            st.caption(
                f":material/add_box: {job.name}: bitiş {ui.clock(job.completion)}, "
                f"termin {ui.clock(job.due_date)}{late}"
            )

    st.subheader("Önce ve sonra")
    x_max = max(comparison.before.makespan, comparison.after.makespan)
    for title, scenario, result in [
        ("Önce: etkin plan", baseline.scenario, baseline.result),
        ("Sonra: simülasyon", simulation.scenario, simulation.result),
    ]:
        st.caption(title)
        ui.gantt(
            [row.model_dump() for row in result.schedule],
            machines=[m.name for m in scenario.machines],
            job_label=lambda j, jobs=scenario.jobs: jobs[j].name,
            x_title="t=0 referansından dakika",
            x_max=x_max,
            downtimes=downtime_bands(scenario),
        )

    st.subheader("Etkilenen işler")
    ui.impact_table(comparison)

    st.subheader("Simülasyon sonrası şu an")
    ui.dispatch_board(outcome.dispatch)

    with st.container(border=True):
        st.markdown("**:material/save: Planı kaydet**")
        st.caption(
            "Kaydedilen plan yeni sürüm olur ve Plan sayfasında etkin plan olarak görünür. "
            "Önceki sürümler silinmez."
        )
        approver = st.text_input("Onaylayan", placeholder="Ad Soyad")
        confirmed = st.checkbox("Bu planı yeni sürüm olarak kaydetmeyi onaylıyorum")
        if st.button(
            "Planı kaydet",
            type="primary",
            disabled=not (approver.strip() and confirmed),
        ):
            try:
                version = save_plan(simulation, parent_version_id, approver.strip())
            except PlanVersionConflict:
                st.error(
                    "Plan bu arada değişti. Sayfayı yenileyip yeniden simüle edin.",
                    icon=":material/sync_problem:",
                )
                return
            st.session_state.pop(state_key, None)
            st.session_state["saved_version"] = version
            st.rerun()


def simulation_page():
    baseline, label, saved = current_plan()
    st.title("Simülasyon")
    st.caption(
        f"Etkin plan: {label} · simülasyon planı değiştirmez; yeni sürüm yalnız kaydettiğinizde oluşur"
    )
    if version := st.session_state.pop("saved_version", None):
        st.success(
            f"{version} sürümü kaydedildi ve etkin plan oldu.",
            icon=":material/verified:",
        )

    request = change_form(baseline)
    if request is not None:
        try:
            st.session_state["simulation"] = (
                baseline.version_id,
                run(baseline, request),
            )
        except ValueError as error:
            st.error(explain_error(error), icon=":material/error:")
            st.session_state.pop("simulation", None)

    stored = st.session_state.get("simulation")
    if stored and stored[0] == baseline.version_id:
        st.divider()
        simulation_result(baseline, stored[1], baseline.version_id if saved else None)


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


# Hakkında (WP-5N): what is reused from open source and what the team built.
# Laid out as a 4×3 grid: the flow runs right along the top row, then back along the bottom.
ARCHITECTURE = """
digraph {
  graph [rankdir=LR bgcolor="transparent" nodesep=0.5 ranksep=0.7 fontname="Helvetica"]
  node [shape=box style="rounded,filled" fontname="Helvetica" fontsize=13 fontcolor="#1F2937" color="#CBD5E1" width=1.9 height=0.65]
  edge [color="#94A3B8" arrowsize=0.8 fontname="Helvetica" fontsize=10 fontcolor="#64748B"]
  data [label="Plan, sipariş, duruş\n(JSON, SQLite)" fillcolor="#FED7AA"]
  gemma [label="Gemma (yerel)\ntalep ve açıklama" fillcolor="#E9D5FF"]
  env [label="Çizelgeleme ortamı\nBrandimarte" fillcolor="#E2E8F0"]
  rules [label="Atölye kuralları\n(Pydantic)" fillcolor="#FED7AA"]
  store [label="Onaylı plan\nsürümleri" fillcolor="#FED7AA"]
  solver [label="CP-SAT çözücü" fillcolor="#BFDBFE"]
  ui [label="Streamlit arayüzü\nonay ve kayıt" fillcolor="#FED7AA"]
  check [label="Bağımsız\ndoğrulayıcı" fillcolor="#FED7AA"]
  compare [label="Önce / sonra\nkarşılaştırma" fillcolor="#FED7AA"]
  {rank=same; data; gemma}
  {rank=same; env; rules; store}
  {rank=same; solver; ui}
  {rank=same; check; compare}
  data -> rules -> solver -> check
  env -> solver
  check -> compare
  ui -> compare [dir=back]
  store -> ui [dir=back]
  gemma -> rules [label="onaylı taslak"]
  gemma -> compare [dir=back style=dashed label="hesaplanan bulgular"]
}
"""
ORIGINS = {"Açık kaynak": "gray", "Açık kaynak + ekip": "blue", "Ekip": "orange"}
STATES = {
    "Çalışıyor": "green",
    "Deneysel": "violet",
    "Deney": "violet",
    "Bekliyor": "gray",
}
COMPONENTS = [
    (
        "Çizelgeleme ortamı",
        "İş, operasyon ve makine yapıları; benchmark ayrıştırıcıları",
        "Açık kaynak",
        "Çalışıyor",
        "scheduling_environment/",
    ),
    (
        "Brandimarte örnekleri",
        "Mk01–Mk10 esnek atölye problemleri",
        "Açık kaynak",
        "Çalışıyor",
        "external/job_shop_benchmark/",
    ),
    (
        "CP-SAT çözücü",
        "Makine ataması ve zamanlama; süre sınırı ve çözüm durumu",
        "Açık kaynak + ekip",
        "Çalışıyor",
        "core/cpsat_solver.py",
    ),
    (
        "Atölye kuralları",
        "Termin, duruş, başlamış ve tamamlanmış işlemler",
        "Ekip",
        "Çalışıyor",
        "core/workshop_model.py",
    ),
    (
        "Bağımsız doğrulayıcı",
        "Çizelgeyi çözücüden ayrı denetler",
        "Ekip",
        "Çalışıyor",
        "core/validation.py",
    ),
    (
        "Sipariş ve duruş simülasyonu",
        "Önce/sonra karşılaştırma ve etkilenen işler",
        "Ekip",
        "Çalışıyor",
        "core/scenarios.py, core/downtime.py",
    ),
    (
        "Veri hattı",
        "Plan → değişiklik → çözüm → tezgâh durumu",
        "Ekip",
        "Çalışıyor",
        "core/pipeline.py",
    ),
    (
        "Plan sürümleri",
        "Onaylı planları SQLite'ta sürüm olarak saklar",
        "Ekip",
        "Çalışıyor",
        "core/sqlite_repository.py",
    ),
    (
        "Gemma talep ve açıklama",
        "Türkçe talebi siparişe çevirir, sonucu açıklar",
        "Ekip",
        "Deneysel",
        "core/llm/",
    ),
    (
        "LangGraph akışı",
        "Soru ve onay için duraklayan sipariş akışı",
        "Ekip",
        "Deneysel",
        "core/llm/graph.py",
    ),
    (
        "Süre tahmini",
        "TabPFN ve diğer modellerin medyanla karşılaştırması; planda kullanılmaz",
        "Ekip",
        "Deney",
        "experiments/tabpfn/",
    ),
    (
        "Benzer iş arama",
        "EmbeddingGemma ile geçmiş iş özetlerinde arama",
        "Ekip",
        "Bekliyor",
        "—",
    ),
    (
        "Arayüz",
        "Streamlit sayfaları, Altair Gantt ve bileşenler",
        "Ekip",
        "Çalışıyor",
        "ui/",
    ),
]
LIBRARIES = [
    ("ortools", "OR-Tools", "Apache-2.0", "CP-SAT çözücü"),
    ("streamlit", "Streamlit", "Apache-2.0", "Arayüz"),
    ("altair", "Altair", "BSD-3-Clause", "Gantt ve grafikler"),
    ("pydantic", "Pydantic", "MIT", "Veri sözleşmeleri"),
    ("pandas", "pandas", "BSD-3-Clause", "Tablolar"),
    ("langgraph", "LangGraph", "MIT", "Gemma akışı"),
]
TEAM = [
    (
        "Atakan Yılmaz",
        "atakhanyilmaz",
        "Çözücü ve Brandimarte kıyası, dinamik yeniden çizelgeleme, Gemma akışı, süre tahmini modelleri",
    ),
    (
        "Yunus",
        "yunussfr",
        "Veri doğrulama, SQLite plan sürümleri, veri hattı, EmbeddingGemma arama",
    ),
    (
        "Nazlısu Başak",
        "nazlisu07",
        "Arayüz ve bileşenler, Gantt ve grafikler, rota onayı, simülasyon ve Gemma ekranları, tutorial'lar",
    ),
]
LIMITS = [
    "Tezgâhlar kesintisiz çalışır varsayılır; vardiya, mola ve takvim yok.",
    "Operasyonlar bölünemez; hazırlık süresi sıraya bağlı değildir.",
    "Demo planı ve demo sipariş açıkça etiketli örnek verilerdir; gerçek işletme ölçümü yoktur.",
    "Brandimarte süreleri benchmark birimidir, dakika değildir.",
    "Gemma akışı deneyseldir; model yoksa her şey elle girişle çalışır.",
    "Süre tahmini modelleri medyanı güvenilir biçimde geçemedi; planlama onaylı süreleri kullanır.",
]


def library_version(package):
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return "kurulu değil"


def about_page():
    st.title("Hakkında")
    st.write(
        "PickWise, fason imalat atölyeleri için yerelde çalışan bir üretim planlama "
        "yardımcısıdır. Temel soru şudur: bu yeni siparişi mevcut plana eklersem ne zaman "
        "biter, hangi işler gecikir ve başka bir uygun makine sonucu değiştirir mi?"
    )
    does, does_not = st.columns(2)
    with does.container(border=True, height="stretch"):
        st.markdown("**:material/check_circle: Ne yapar**")
        st.markdown(
            "- Planı CP-SAT ile çözer, sonucu bağımsız doğrulayıcıdan geçirir\n"
            "- Yeni sipariş ve makine duruşunun etkisini önce/sonra gösterir\n"
            "- Rota ve sürelerin kaynağını rozetle belirtir\n"
            "- Onaylanan planı yeni sürüm olarak saklar"
        )
    with does_not.container(border=True, height="stretch"):
        st.markdown("**:material/do_not_disturb_on: Ne yapmaz**")
        st.markdown(
            "- Ölçülmemiş tasarruf veya verimlilik iddiası üretmez\n"
            "- Gemma'ya süre, saat ya da makine seçtirmez\n"
            "- Onayınız olmadan planı değiştirmez veya kaydetmez\n"
            "- Verileri buluta göndermez; model yerel Ollama'da çalışır"
        )

    st.subheader("Mimari")
    st.graphviz_chart(ARCHITECTURE)
    st.caption(
        "Turuncu: ekibin geliştirdiği · Mavi: açık kaynak üzerine ekip uyarlaması · "
        "Gri: açık kaynak · Mor: yerel dil modeli"
    )

    st.subheader("Açık kaynak ve ekip katkısı")
    ui.table(
        [
            {
                "Bileşen": name,
                "Ne yapar": what,
                "Kaynak": [origin],
                "Durum": [state],
                "Kod": path,
            }
            for name, what, origin, state, path in COMPONENTS
        ],
        column_config={
            "Kaynak": ui.pill_column("Kaynak", ORIGINS),
            "Durum": ui.pill_column("Durum", STATES),
            "Kod": st.column_config.TextColumn("Kod", width="medium"),
        },
    )
    st.caption(
        "Çizelgeleme ortamı, Brandimarte verileri ve CP-SAT modelinin temeli "
        "[TU Eindhoven Job Shop Scheduling Benchmark](https://github.com/ai-for-decision-making-tue/"
        f"Job_Shop_Scheduling_Benchmark_Environments_and_Instances) deposundan alınmıştır "
        f"(commit `{COMMIT[:7]}`, MIT lisansı)."
    )

    st.subheader("Kütüphaneler ve modeller")
    left, right = st.columns([3, 2])
    with left:
        ui.table(
            [
                {
                    "Kütüphane": name,
                    "Sürüm": library_version(package),
                    "Lisans": license,
                    "Kullanım": use,
                }
                for package, name, license, use in LIBRARIES
            ]
        )
    with right.container(border=True):
        st.markdown("**:material/gavel: Model lisansları**")
        st.markdown(
            "- **Gemma:** Google Gemma kullanım şartları; ağırlıklar Ollama ile yerelde\n"
            "- **TabPFN v2:** Prior Labs ağırlık lisansı, `experiments/tabpfn/docs/licenses`\n"
            "- Deponun MIT lisansı dış veri ve modelleri kapsamaz."
        )

    st.subheader("Ekip")
    for column, (name, handle, work) in zip(st.columns(len(TEAM)), TEAM):
        with column.container(border=True, height="stretch"):
            st.markdown(f"**{name}**")
            st.caption(f"[@{handle}](https://github.com/{handle})")
            st.write(work)

    st.subheader("Varsayımlar ve sınırlamalar")
    st.markdown("\n".join(f"- {limit}" for limit in LIMITS))
    st.caption("Sürüm 0.1 (demo) · Code_Night")

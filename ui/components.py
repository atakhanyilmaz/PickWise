"""Reusable Streamlit building blocks. Pages compose these; no scheduling logic lives here."""

from datetime import date, datetime, time, timedelta
from math import isfinite

import altair as alt
import pandas as pd
import streamlit as st
from pydantic import ValidationError

from core.domain_rules import DurationSource, JobModel, RouteSource
from core.scenarios import status_message

STATUS_SHORT = {
    "OPTIMAL": "Optimal",
    "FEASIBLE": "Uygulanabilir",
    "INFEASIBLE": "Plan yok",
    "UNKNOWN": "Sonuç yok",
    "MODEL_INVALID": "Model hatası",
}

# One visual vocabulary for both RouteSource and DurationSource values: (label, badge color, icon).
SOURCES = {
    RouteSource.USER_APPROVED: ("Kullanıcı onaylı", "green", ":material/verified:"),
    DurationSource.USER_INPUT: ("Kullanıcı süresi", "green", ":material/person:"),
    RouteSource.USER_PROPOSED: ("Onay bekliyor", "blue", ":material/pending:"),
    RouteSource.RETROSPECTIVE: ("Retrospektif kayıt", "orange", ":material/history:"),
    DurationSource.HISTORICAL_MEDIAN: ("Geçmiş medyan", "orange", ":material/history:"),
    DurationSource.TABPFN_ESTIMATE: ("TabPFN tahmini", "violet", ":material/insights:"),
    DurationSource.BENCHMARK: ("Benchmark", "gray", ":material/science:"),
    RouteSource.DEMO_ASSUMPTION: ("Demo varsayımı", "gray", ":material/science:"),
}
SOURCE_LABELS = {source.value: label for source, (label, _, _) in SOURCES.items()}
BADGE_HEX = {
    "green": "#21c354",
    "blue": "#3d9df3",
    "orange": "#ff9f43",
    "violet": "#9a6dd7",
    "gray": "#6b7280",
}


def source_badge(source):
    label, color, icon = SOURCES[source]
    st.badge(label, icon=icon, color=color)


def pill_column(title, colors):
    """Read-only table column drawing each cell's labels as pills; colors maps label → badge color."""
    return st.column_config.MultiselectColumn(
        title,
        options=list(colors),
        color=[BADGE_HEX[color] for color in colors.values()],
        disabled=True,
    )


def source_column(title):
    """Table column that renders source labels as colored pills, matching source_badge."""
    return pill_column(title, {label: color for label, color, _ in SOURCES.values()})


# Wordmark drawn inline (no image file): three Gantt-like bars and the product name.
# Orange reads on both the light and the dark sidebar.
LOGO = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="190" height="34" viewBox="0 0 190 34">'
    '<g fill="#EA580C"><rect x="0" y="5" width="16" height="6" rx="2"/>'
    '<rect x="7" y="14" width="18" height="6" rx="2"/><rect x="3" y="23" width="12" height="6" rx="2"/></g>'
    '<text x="34" y="25" fill="#EA580C" font-family="Source Sans Pro, Helvetica, Arial, sans-serif" '
    'font-size="22" font-weight="700" letter-spacing="1.5">PICKWISE</text></svg>'
)


def brand():
    st.logo(LOGO, size="large")


def sidebar_settings(plan_label, plan_saved):
    """Shared settings; values are read back through st.session_state."""
    with st.sidebar:
        st.markdown("**:material/tune: Plan ayarları**")
        left, right = st.columns(2)
        left.date_input(
            "Başlangıç tarihi", date(2026, 10, 19), key="t0_date", format="DD.MM.YYYY"
        )
        right.time_input("Saat", time(8, 0), key="t0_time")
        st.slider("Çözücü süre sınırı (sn)", 1, 60, 10, key="time_limit")

        st.markdown("**:material/inventory_2: Etkin plan**")
        st.badge(
            plan_label,
            icon=":material/verified:" if plan_saved else ":material/science:",
            color="green" if plan_saved else "gray",
        )

        st.divider()
        st.caption(
            ":material/info: Kesintisiz çalışma varsayılır; vardiya ve mola yok."
        )
        st.caption(
            ":material/contrast: Gündüz / gece modu: sağ üstte ⋮ → Light, Dark, System"
        )


def clock(minutes):
    """Minutes from t=0 shown as a wall-clock time from the sidebar's plan start."""
    if minutes is None:
        return "—"
    t0 = datetime.combine(st.session_state["t0_date"], st.session_state["t0_time"])
    return (t0 + timedelta(minutes=int(minutes))).strftime("%d.%m %H:%M")


def short_clock(minutes):
    """Time only on the plan's start day; date and time once the plan runs past midnight."""
    full = clock(minutes)
    return full[-5:] if full[:5] == clock(0)[:5] else full


def metric_row(items):
    """items: list of (label, value, caption or None)."""
    for column, (label, value, caption) in zip(st.columns(len(items)), items):
        column.metric(label, value)
        if caption:
            column.caption(caption)


def status_metric(status):
    """(value, caption) pair for a solver status, using the team's Turkish messages."""
    return STATUS_SHORT.get(status, status), status_message(status)


def gantt(rows, machines, job_label, x_title, *, x_max=None, downtimes=()):
    """Gantt from schedule rows (job, operation, machine, start, end); machines[i] names machine index i.

    x_max pins the time axis so two charts line up; downtimes are (machine name, start, end)
    intervals drawn as gray bands behind the operations.
    """
    frame = pd.DataFrame(
        {
            "Makine": [machines[r["machine"]] for r in rows],
            "İş": [job_label(r["job"]) for r in rows],
            "Operasyon": [f"O{r['operation'] + 1}" for r in rows],
            "Başlangıç": [r["start"] for r in rows],
            "Bitiş": [r["end"] for r in rows],
        }
    )
    frame["Süre"] = frame["Bitiş"] - frame["Başlangıç"]
    x_scale = alt.Scale(domain=[0, x_max]) if x_max else alt.Undefined
    y = alt.Y("Makine:N", scale=alt.Scale(domain=list(machines)), title=None)
    base = alt.Chart(frame).encode(
        x=alt.X("Başlangıç:Q", title=x_title, scale=x_scale),
        x2="Bitiş:Q",
        y=y,
    )
    layers = []
    if downtimes:
        blocked = pd.DataFrame(downtimes, columns=["Makine", "Başlangıç", "Bitiş"])
        layers.append(
            alt.Chart(blocked)
            .mark_bar(height={"band": 0.9}, color="#94A3B8", opacity=0.35)
            .encode(
                x=alt.X("Başlangıç:Q", scale=x_scale),
                x2="Bitiş:Q",
                y=y,
                tooltip=[
                    alt.Tooltip("Makine"),
                    alt.Tooltip("Başlangıç", title="Duruş başı"),
                    alt.Tooltip("Bitiş", title="Duruş sonu"),
                ],
            )
        )
    bars = base.mark_bar(height={"band": 0.7}, cornerRadius=2).encode(
        color=alt.Color(
            "İş:N",
            sort=[job_label(j) for j in sorted({r["job"] for r in rows})],
            scale=alt.Scale(scheme="tableau10"),
            legend=alt.Legend(orient="top", title=None),
        ),
        tooltip=["İş", "Operasyon", "Makine", "Başlangıç", "Bitiş", "Süre"],
    )
    labels = base.mark_text(align="left", dx=4, color="white", fontSize=11).encode(
        text="Operasyon"
    )
    height = 44 * len(machines)
    chart = alt.layer(*layers, bars, labels).properties(height=height)
    st.altair_chart(chart, width="stretch", height=height + 90)


def dispatch_board(statuses, per_row=4):
    """One card per machine: what it runs at the chosen moment and what comes next."""
    columns = [
        column
        for start in range(0, len(statuses), per_row)
        for column in st.columns(per_row)
    ]
    for column, status in zip(columns, statuses):
        with column.container(border=True):
            st.markdown(f"**{status.machine_name}**")
            if status.current:
                st.badge("Çalışıyor", icon=":material/play_arrow:", color="green")
                st.markdown(
                    f"{status.current.job_name} · {status.current.operation_name}"
                )
                st.caption(f"Biter: {clock(status.current.end)}")
            else:
                st.badge("Boşta", icon=":material/pause:", color="gray")
            if status.next:
                st.caption(
                    f"Sırada: {status.next.job_name} · {status.next.operation_name}, "
                    f"{clock(status.next.start)}"
                )
            else:
                st.caption("Sırada iş yok")


def table(records, column_config=None):
    st.dataframe(
        pd.DataFrame(records),
        hide_index=True,
        width="stretch",
        column_config=column_config,
    )


def route_editor(job, machines, key):
    """Editable route: one row per operation in order, one minutes column per machine (blank = not eligible)."""
    names = [m.name for m in machines]
    rows = [
        {
            "Operasyon": op.name,
            **{m.name: op.processing_times.get(m.machine_id) for m in machines},
        }
        for op in (job.operations if job else [])
    ]
    frame = pd.DataFrame(rows or [{}], columns=["Operasyon", *names])
    # float keeps blank cells as NaN, which the editor shows empty (not "None").
    frame = frame.astype({"Operasyon": "string", **dict.fromkeys(names, "float")})
    return st.data_editor(
        frame,
        key=key,
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        column_config={
            "Operasyon": st.column_config.TextColumn("Operasyon", required=True),
            **{
                name: st.column_config.NumberColumn(
                    f"{name} (dk)", min_value=1, step=1, format="%d"
                )
                for name in names
            },
        },
    )


def job_from_route(frame, *, name, base, machines, job_id):
    """Turn edited route rows into a validated JobModel draft; returns (job or None, problems).

    An operation keeps its original duration source only if its name and times are unchanged;
    any edit makes it a user-entered duration. The route stays unapproved until approve() is called.
    """
    problems, operations = [], []
    original = base.operations if base else []
    for index, row in enumerate(frame.to_dict("records"), start=1):
        label = "" if pd.isna(row.get("Operasyon")) else str(row["Operasyon"]).strip()
        times = {}
        for machine in machines:
            value = row.get(machine.name)
            if pd.isna(value):
                continue
            try:
                numeric = float(value)
                valid = (
                    not isinstance(value, bool)
                    and isfinite(numeric)
                    and numeric > 0
                    and numeric.is_integer()
                )
            except (TypeError, ValueError, OverflowError):
                valid = False
            if not valid:
                problems.append(
                    f"{index}. satır: {machine.name} süresi pozitif tam sayı dakika olmalı."
                )
                continue
            times[machine.machine_id] = int(numeric)
        if not label and not times:
            continue
        if not label:
            problems.append(f"{index}. satır: operasyon adı yazın.")
        if not times:
            problems.append(f"{index}. satır: en az bir tezgâh için süre girin.")
        previous = original[index - 1] if index <= len(original) else None
        unchanged = (
            previous and previous.name == label and previous.processing_times == times
        )
        operations.append(
            {
                "operation_id": index,
                "name": label or f"Operasyon {index}",
                "processing_times": times or {machines[0].machine_id: 1},
                "duration_source": previous.duration_source
                if unchanged
                else DurationSource.USER_INPUT,
            }
        )
    if not name.strip():
        problems.append("Sipariş adı yazın.")
    if not operations:
        problems.append("En az bir operasyon ekleyin.")
    if problems:
        return None, problems
    edited = base is None or [op["duration_source"] for op in operations] != [
        op.duration_source for op in base.operations
    ]
    try:
        job = JobModel(
            job_id=job_id,
            name=name.strip(),
            operations=operations,
            route_source=RouteSource.USER_PROPOSED if edited else base.route_source,
            deadline=base.deadline if base else None,
            due_date=base.due_date if base else None,
            release_time=base.release_time if base else 0,
        )
    except ValidationError as error:
        return None, [e["msg"] for e in error.errors()]
    return job, []


def approve(job):
    """The only place a route becomes USER_APPROVED; call it after an explicit user action."""
    return job.model_copy(update={"route_source": RouteSource.USER_APPROVED}, deep=True)


def model_error_chart(frame, value, unit, highlight):
    """Horizontal bars of one error metric per model, best first; `highlight` gets the accent color."""
    chart = (
        alt.Chart(frame)
        .mark_bar(cornerRadius=2)
        .encode(
            x=alt.X(
                f"{value}:Q", title=f"Ortalama mutlak hata ({unit}) · düşük daha iyi"
            ),
            y=alt.Y("Model:N", sort="x", title=None),
            color=alt.condition(
                alt.datum.Model == highlight,
                alt.value("#EA580C"),
                alt.value("#94A3B8"),
            ),
            tooltip=["Model", alt.Tooltip(f"{value}:Q", format=".2f")],
        )
    )
    st.altair_chart(chart, width="stretch", height=36 * len(frame) + 60)


def prediction_scatter(frame, unit):
    """Actual vs predicted points with the y = x line where a perfect model would sit."""
    top = float(max(frame["Gerçek"].max(), frame["Tahmin"].max())) * 1.05
    diagonal = (
        alt.Chart(pd.DataFrame({"x": [0, top], "y": [0, top]}))
        .mark_line(strokeDash=[4, 4], color="#94A3B8")
        .encode(x="x:Q", y="y:Q")
    )
    points = (
        alt.Chart(frame)
        .mark_circle(size=90, color="#EA580C", opacity=0.85)
        .encode(
            x=alt.X(
                "Gerçek:Q",
                title=f"Gerçekleşen ({unit})",
                scale=alt.Scale(domain=[0, top]),
            ),
            y=alt.Y(
                "Tahmin:Q", title=f"Tahmin ({unit})", scale=alt.Scale(domain=[0, top])
            ),
            tooltip=[
                "İş",
                "Parça",
                alt.Tooltip("Gerçek:Q", format=".1f"),
                alt.Tooltip("Tahmin:Q", format=".1f"),
            ],
        )
    )
    st.altair_chart(diagonal + points, width="stretch", height=380)


def clock_input(label, default_minute, key):
    """Date + time picker returning minutes from the sidebar's plan start (t=0)."""
    t0 = datetime.combine(st.session_state["t0_date"], st.session_state["t0_time"])
    default = t0 + timedelta(minutes=int(default_minute))
    day, hour = st.columns(2)
    picked_day = day.date_input(
        label, default.date(), key=f"{key}-date", format="DD.MM.YYYY"
    )
    picked_time = hour.time_input("Saat", default.time(), key=f"{key}-time", step=300)
    return int((datetime.combine(picked_day, picked_time) - t0).total_seconds() // 60)


def comparison_metrics(comparison):
    """Before → after plan figures; a rise in finish time or delays is shown as worse."""
    before, after = comparison.before, comparison.after
    columns = st.columns(4)
    columns[0].metric(
        "Tüm işler biter",
        short_clock(after.makespan),
        f"{after.makespan - before.makespan:+d} dk",
        delta_color="inverse",
        help=f"Önce {clock(before.makespan)}",
    )
    columns[1].metric(
        "Geç biten mevcut iş",
        comparison.delayed_existing_job_count,
        help="Önceki plana göre daha geç biten mevcut iş sayısı",
    )
    columns[2].metric(
        "Termini aşan iş",
        after.late_job_count,
        f"{after.late_job_count - before.late_job_count:+d}",
        delta_color="inverse",
    )
    columns[3].metric(
        "Toplam termin gecikmesi",
        f"{after.total_tardiness} dk",
        f"{after.total_tardiness - before.total_tardiness:+d} dk",
        delta_color="inverse",
    )


def impact_table(comparison):
    """Every existing job: completion before and after, the shift and soft due-date lateness."""
    table(
        [
            {
                "İş": impact.name,
                "Önce bitiş": clock(impact.before_completion),
                "Sonra bitiş": clock(impact.after_completion),
                "Fark (dk)": impact.completion_delta,
                "Önce gecikme (dk)": impact.before_tardiness,
                "Sonra gecikme (dk)": impact.after_tardiness,
                "Yeri değişen operasyon": impact.changed_operations,
            }
            for impact in comparison.impacts
        ],
        column_config={
            "Fark (dk)": st.column_config.NumberColumn(format="%+d"),
        },
    )


# Gemma assistant (WP-5N). Gemma only structures the request and picks computed facts,
# so every card names where its content came from.
EXPLANATION_ORIGINS = {
    "gemma_selected_facts": ("Gemma seçti", "violet", ":material/auto_awesome:"),
    "computed_fallback": ("Hesaplanan metin", "gray", ":material/calculate:"),
}
LOG_STAGES = {
    "intent": "Araç seçimi",
    "fields": "Alan çıkarımı",
    "field_answer": "Cevap yorumu",
    "operations_followup": "Operasyon cevabı",
    "followup": "Takip cevabı",
    "preflight": "Kural denetimi",
    "tool_execution": "Plan inceleme",
    "error": "Hata",
    "explanation": "Açıklama",
}


def gemma_status(metadata, error):
    """Connection badge for the local model, with the identity the client recorded."""
    if metadata:
        st.badge("Bağlı", icon=":material/check_circle:", color="green")
        st.caption(
            f"{metadata['model_tag']} · {metadata['parameter_size']} · "
            f"{metadata['quantization']}"
        )
        st.caption(
            f"Ollama {metadata['ollama_version']} · yerel, `{metadata['endpoint']}`"
        )
    else:
        st.badge("Bağlı değil", icon=":material/cloud_off:", color="gray")
        st.caption(error)


def proposal_card(order, preserve_completions, machine_names):
    """The order Gemma extracted, exactly as the solver would receive it."""
    job = JobModel.model_validate(order)
    with st.container(border=True):
        st.markdown(f"**:material/assignment: {job.name}**")
        source_badge(job.route_source)
        table(
            [
                {
                    "Sıra": index,
                    "İşlem": op.name,
                    "Makine ve süre": " · ".join(
                        f"{machine_names[m]} {minutes} dk"
                        for m, minutes in op.processing_times.items()
                    ),
                    "Süre kaynağı": [SOURCE_LABELS[op.duration_source.value]],
                }
                for index, op in enumerate(job.operations, 1)
            ],
            column_config={"Süre kaynağı": source_column("Süre kaynağı")},
        )
        if job.deadline is not None:
            st.caption(f":material/flag: Sert termin: {clock(job.deadline)}")
        elif job.due_date is not None:
            st.caption(f":material/flag: Hedef termin: {clock(job.due_date)}")
        else:
            st.caption(":material/flag: Termin yok")
        st.caption(
            ":material/lock: Mevcut işlerin bitiş saatleri korunur"
            if preserve_completions
            else ":material/lock_open: Mevcut işler gerekirse kayabilir"
        )
        st.caption(
            "Makine ve süreler yalnız sizin yazdıklarınızdan alınır; Gemma süre veya makine üretmez."
        )


def explanation_card(explanation):
    """Turkish summary built from computed facts; the badge tells who picked them."""
    label, color, icon = EXPLANATION_ORIGINS[explanation["origin"]]
    with st.container(border=True):
        st.markdown("**:material/chat: Sonucun açıklaması**")
        st.badge(label, icon=icon, color=color)
        st.markdown("\n".join(f"- {line}" for line in explanation["text"].splitlines()))
        st.caption(
            "Her cümle çözücü sonucundan şablonla yazılır. Gemma yalnız hangi bulguların "
            "gösterileceğini seçer; seçim geçersizse hesaplanan metnin tamamı gösterilir."
        )


def model_log(audit, explanation=None):
    """Which step asked the model, with which model and prompt version (AGENTS.md §4)."""
    stages = list(audit)
    if explanation:
        stages.append(
            {"stage": "explanation", "metadata": explanation["model_metadata"]}
        )
    rows = []
    for stage in stages:
        meta = stage.get("metadata") or {}
        model = meta.get("model_tag") or ("Kod kuralı" if stage.get("origin") else "—")
        rows.append(
            {
                "Adım": LOG_STAGES.get(stage["stage"], stage["stage"]),
                "Model": model,
                "İstem sürümü": meta.get("prompt_version", "—"),
                "Süre (sn)": round(meta["total_duration"] / 1e9, 1)
                if meta.get("total_duration")
                else None,
                "Not": meta.get("fallback_reason") or stage.get("type") or "",
            }
        )
    table(rows)

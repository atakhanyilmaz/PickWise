"""Reusable Streamlit building blocks. Pages compose these; no scheduling logic lives here."""

from datetime import date, datetime, time, timedelta

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


def source_column(title):
    """Table column that renders source labels as colored pills, matching source_badge."""
    labels = list(dict.fromkeys(SOURCE_LABELS.values()))
    colors = {label: BADGE_HEX[color] for label, color, _ in SOURCES.values()}
    return st.column_config.MultiselectColumn(
        title, options=labels, color=[colors[label] for label in labels], disabled=True
    )


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


def metric_row(items):
    """items: list of (label, value, caption or None)."""
    for column, (label, value, caption) in zip(st.columns(len(items)), items):
        column.metric(label, value)
        if caption:
            column.caption(caption)


def status_metric(status):
    """(value, caption) pair for a solver status, using the team's Turkish messages."""
    return STATUS_SHORT.get(status, status), status_message(status)


def gantt(rows, machines, job_label, x_title):
    """Gantt from schedule rows (job, operation, machine, start, end); machines[i] names machine index i."""
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
    base = alt.Chart(frame).encode(
        x=alt.X("Başlangıç:Q", title=x_title),
        x2="Bitiş:Q",
        y=alt.Y("Makine:N", scale=alt.Scale(domain=list(machines)), title=None),
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
    chart = (bars + labels).properties(height=height)
    st.altair_chart(chart, width="stretch", height=height + 90)


def dispatch_board(statuses):
    """One card per machine: what it runs at the chosen moment and what comes next."""
    for column, status in zip(st.columns(len(statuses)), statuses):
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
        times = {
            m.machine_id: int(row[m.name])
            for m in machines
            if not pd.isna(row.get(m.name))
        }
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

"""Reusable Streamlit building blocks. Pages compose these; no scheduling logic lives here."""

from datetime import date, datetime, time, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from core.scenarios import status_message

STATUS_SHORT = {
    "OPTIMAL": "Optimal",
    "FEASIBLE": "Uygulanabilir",
    "INFEASIBLE": "Plan yok",
    "UNKNOWN": "Sonuç yok",
    "MODEL_INVALID": "Model hatası",
}


def sidebar_settings(active_plan):
    """Shared settings; values are read back through st.session_state."""
    with st.sidebar:
        st.divider()
        st.caption("Plan başlangıcı (t=0)")
        left, right = st.columns(2)
        left.date_input("Tarih", date(2026, 10, 19), key="t0_date", format="DD.MM.YYYY")
        right.time_input("Saat", time(8, 0), key="t0_time")
        st.slider("Çözücü süre sınırı (sn)", 1, 60, 10, key="time_limit")
        st.caption(f"Etkin plan: {active_plan}")
        st.caption("Kesintisiz çalışma varsayılır; vardiya ve mola yok.")


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


def table(records):
    st.dataframe(pd.DataFrame(records), hide_index=True, width="stretch")

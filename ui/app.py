"""Run from the repo root: streamlit run ui/app.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from ui import components as ui  # noqa: E402
from ui import pages  # noqa: E402

st.set_page_config(
    page_title="PickWise", page_icon=":material/view_timeline:", layout="wide"
)
navigation = st.navigation(
    [
        st.Page(
            pages.plan_page, title="Plan", icon=":material/view_timeline:", default=True
        ),
        st.Page(pages.benchmark_page, title="Benchmark", icon=":material/bar_chart:"),
        st.Page(pages.about_page, title="Hakkında", icon=":material/info:"),
    ]
)
st.sidebar.title("PICKWISE")
ui.sidebar_settings(active_plan=pages.current_plan()[1])
navigation.run()

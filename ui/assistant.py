"""Gemma assistant page (WP-5N): Turkish request → questions → approval → simulation → explanation.

The page only drives core.llm.graph. Gemma structures the request and picks computed facts;
CP-SAT calculates every number, and nothing runs or is saved without an explicit click.
"""

import re
from uuid import uuid4

import streamlit as st
from langgraph.types import Command

from core.llm.graph import build_order_graph
from core.llm.ollama_client import ModelUnavailable, OllamaClient
from core.pipeline import MachineStatus, PipelineResult
from core.scenarios import SimulationResult
from ui import components as ui
from ui import pages

# Preferred order and short notes for known Gemma tags; the picker lists only tags
# installed on this computer. e4b and e2b results: team Gemma fixtures (ADR 013).
MODELS = {
    "gemma4:e4b": "Gemma 4 E4B · ekip testleri 29/30",
    "gemma4:e2b": "Gemma 4 E2B · ekibin değerlendirdiği model",
    "gemma4:12b": "Gemma 4 12B",
    "gemma4:26b": "Gemma 4 26B (MoE)",
    "gemma3:27b": "Gemma 3 27B",
    "gemma3:12b": "Gemma 3 12B",
    "gemma3:4b": "Gemma 3 4B",
}
RECOMMENDED = "gemma4:e4b"

CONNECTION_ERRORS = {
    "Local Ollama request failed": "Ollama çalışmıyor. Terminalde `ollama serve` ile başlatın.",
    "Model is not installed": "Bu model bu bilgisayarda kurulu değil.",
    "Cloud-backed models": "Bulut üzerinden çalışan modeller desteklenmez.",
    "not identified as Gemma": "Seçilen model Gemma değil.",
}


def examples(scenario):
    """Sample requests naming the active plan's own machines (full name or 'M4' style id)."""
    first, second = scenario.machines[0].name, scenario.machines[-1].name
    return [
        f"Yeni sipariş: {first} üzerinde 45 dakika işlem. Mevcut bitişleri koru.",
        f"Yeni sipariş: {second} üzerinde işlem yapacağız.",
        "Şu an kaç iş bekliyor?",
    ]


@st.cache_data(ttl=30, show_spinner=False)
def installed_models():
    """Gemma chat tags on the local Ollama; None when Ollama is not running."""
    try:
        tags = OllamaClient()._request("/api/tags").get("models", [])
    except ModelUnavailable:
        return None
    return [
        tag["name"]
        for tag in tags
        if "gemma" in tag["name"].lower() and "embed" not in tag["name"].lower()
    ]


def model_options(installed):
    """Installed Gemma tags, known models first in preference order."""
    order = list(MODELS)
    return sorted(
        installed,
        key=lambda tag: (
            tag not in MODELS,
            order.index(tag) if tag in MODELS else 0,
            tag,
        ),
    )


def model_label(tag):
    return f"{tag} — {MODELS[tag]}" if tag in MODELS else tag


@st.cache_resource(ttl=60, show_spinner=False)
def connect(model):
    """(client, metadata, error); the client itself checks the model is local and Gemma."""
    client = OllamaClient(model)
    try:
        return client, client.metadata(), None
    except ModelUnavailable as error:
        reason = next(
            (text for key, text in CONNECTION_ERRORS.items() if key in str(error)),
            str(error),
        )
        return None, None, reason.format(model=model)


def new_chat(baseline, client, model):
    return {
        "graph": build_order_graph(
            baseline, client, time_limit=st.session_state["time_limit"]
        ),
        "config": {"configurable": {"thread_id": uuid4().hex}},
        "plan": baseline.version_id,
        "active_baseline": baseline,
        "client": client,
        "model": model,
        "messages": [],
        "pending": None,
        "audit": [],
        "explanation": None,
        "outcome": None,
        "done": False,
    }


def step(chat, baseline, payload, said):
    """Send one user turn (a request, an answer or a decision) and record what came back."""
    if chat["done"] and isinstance(payload, dict) and "text" in payload:
        chat["graph"] = build_order_graph(
            chat["active_baseline"],
            chat["client"],
            time_limit=st.session_state["time_limit"],
        )
        chat["config"] = {"configurable": {"thread_id": uuid4().hex}}
        chat["done"] = False
    chat["messages"].append(("user", said))
    with st.spinner("Gemma talebi okuyor…"):
        out = chat["graph"].invoke(payload, chat["config"])
    chat["audit"] = (out.get("session") or {}).get("audit", [])
    interrupts = out.get("__interrupt__")
    chat["pending"] = interrupts[0].value if interrupts else None
    if chat["pending"] and chat["pending"]["kind"] == "question":
        chat["messages"].append(
            ("assistant", chat["pending"]["questions"][0])
        )
    elif chat["pending"]:
        from core.domain_rules import JobModel

        draft_job = JobModel.model_validate(chat["pending"]["order"])
        st.session_state["gemma_order_draft"] = draft_job
        drafts = list(st.session_state.get("gemma_order_drafts", []))
        drafts = [d for d in drafts if d.job_id != draft_job.job_id] + [draft_job]
        st.session_state["gemma_order_drafts"] = drafts
        chat["messages"].append(
            (
                "assistant",
                "Talebinizi aşağıdaki siparişe çevirdim. Kontrol edip onaylarsanız simüle ederim.",
            )
        )
    elif "explanation" in out:
        from core.scenarios import PlanSnapshot, compare_scenarios

        simulation = SimulationResult.model_validate(out["simulation"])
        if simulation.comparison is not None:
            chat["active_baseline"] = PlanSnapshot(
                version_id=baseline.version_id,
                scenario=simulation.scenario,
                result=simulation.result,
            )
            cumulative = compare_scenarios(
                baseline, simulation.scenario, simulation.result
            )
            simulation = simulation.model_copy(
                update={
                    "baseline_version_id": baseline.version_id,
                    "comparison": cumulative,
                }
            )
        chat["explanation"] = out["explanation"]
        chat["outcome"] = PipelineResult(
            baseline=baseline,
            simulation=simulation,
            at_minute=simulation.scenario.current_time,
            dispatch=[MachineStatus.model_validate(s) for s in out["dispatch"]],
        )
        chat["messages"].append(
            (
                "assistant",
                "Simülasyon tamamlandı. Açıklama ve önce/sonra planı aşağıda.",
            )
        )
    else:
        chat["messages"].append(("assistant", out["message"]))
    chat["done"] = chat["pending"] is None


def model_cards(metadata, error, missing):
    model_card, scope_card, search_card = st.columns(3)
    with model_card.container(border=True, height="stretch"):
        st.markdown("**:material/memory: Yerel model**")
        ui.gemma_status(metadata, error)
        if missing:
            st.code(f"ollama pull {RECOMMENDED}", language="bash")
            st.caption("İndirme bittikten sonra sayfayı yenileyin.")
    with scope_card.container(border=True, height="stretch"):
        st.markdown("**:material/rule: Gemma'nın görevi**")
        st.markdown(
            ":material/check: Türkçe talebi siparişe çevirir  \n"
            ":material/check: Eksik makine, süre veya termini sorar  \n"
            ":material/check: Hesaplanan bulgulardan açıklama seçer  \n"
            ":material/close: Süre, saat veya makine uydurmaz  \n"
            ":material/close: Onayınız olmadan simüle etmez, kaydetmez"
        )
    with search_card.container(border=True, height="stretch"):
        st.markdown("**:material/manage_search: Benzer geçmiş işler**")
        st.badge("Henüz bağlı değil", icon=":material/schedule:", color="gray")
        st.caption(
            "EmbeddingGemma ile geçmiş iş özetlerinde arama (WP-5Y) hazır olduğunda "
            "burada en benzer üç kayıt görünecek. Benzerlik süre veya makine uygunluğunun "
            "kanıtı sayılmaz."
        )


def pending_actions(chat, baseline):
    pending = chat["pending"]
    if pending["kind"] == "question" and pending["choices"]:
        st.caption("Hızlı cevap")
        for column, choice in zip(
            st.columns(len(pending["choices"])), pending["choices"]
        ):
            if column.button(choice, key=f"choice-{choice}", width="stretch"):
                step(chat, baseline, Command(resume=choice), choice)
                st.rerun()
    elif pending["kind"] == "confirmation":
        ui.proposal_card(
            pending["order"],
            pending["preserve_existing_completions"],
            {m.machine_id: m.name for m in baseline.scenario.machines},
        )
        approve, decline = st.columns(2)
        if approve.button(
            "Onayla ve simüle et",
            type="primary",
            icon=":material/play_arrow:",
            width="stretch",
        ):
            from core.domain_rules import JobModel

            approved_job = ui.approve(JobModel.model_validate(pending["order"]))
            st.session_state["approved_order"] = approved_job
            st.session_state["gemma_order_draft"] = approved_job
            drafts = list(st.session_state.get("gemma_order_drafts", []))
            drafts = [d for d in drafts if d.job_id != approved_job.job_id] + [
                approved_job
            ]
            st.session_state["gemma_order_drafts"] = drafts
            step(chat, baseline, Command(resume=True), "Onaylıyorum.")
            st.rerun()
        if decline.button("Vazgeç", icon=":material/close:", width="stretch"):
            step(chat, baseline, Command(resume=False), "Vazgeçtim.")
            st.rerun()


def assistant_page():
    baseline, label, saved = pages.current_plan()
    st.title("Gemma asistanı")
    st.caption(
        f"Etkin plan: {label} · Gemma talebi yapılandırır ve açıklar; hesaplamayı CP-SAT yapar"
    )
    if version := st.session_state.pop("saved_version", None):
        st.success(
            f"{version} sürümü kaydedildi ve etkin plan oldu.",
            icon=":material/verified:",
        )

    installed = installed_models()
    if installed:
        model = st.selectbox(
            "Model",
            model_options(installed),
            format_func=model_label,
            help="Bu bilgisayarda Ollama'ya kurulu Gemma modelleri. Model yerelde çalışır.",
        )
        client, metadata, error = connect(model)
    else:
        model, client, metadata = None, None, None
        error = (
            CONNECTION_ERRORS["Local Ollama request failed"]
            if installed is None
            else "Bu bilgisayarda kurulu Gemma modeli yok. Önerilen model:"
        )
    model_cards(metadata, error, missing=installed == [])

    chat = st.session_state.get("assistant")
    if client is None:
        st.info(
            "Gemma olmadan da sipariş ve makine duruşunu **Planlama → Simülasyon** "
            "sayfasından elle girip aynı hesaplamayı yapabilirsiniz.",
            icon=":material/edit_note:",
        )
        return
    if chat is None or (chat["plan"], chat["model"]) != (baseline.version_id, model):
        chat = st.session_state["assistant"] = new_chat(baseline, client, model)

    st.subheader("Sohbet")
    if not chat["messages"]:
        st.caption("Örnek talepler")
        for example in examples(baseline.scenario):
            if st.button(
                example,
                key=f"example-{example}",
                icon=":material/north_east:",
                type="tertiary",
            ):
                step(chat, baseline, {"text": example}, example)
                st.rerun()
    for role, text in chat["messages"]:
        # "2. işlem ..." must stay a sentence, not become a numbered list item.
        st.chat_message(role).markdown(re.sub(r"(?m)^(\d+)\.", r"\1\\.", text))
    if chat["pending"]:
        pending_actions(chat, baseline)

    if chat["explanation"]:
        ui.explanation_card(chat["explanation"])
    if chat["outcome"]:
        st.divider()
        pages.simulation_result(
            baseline,
            chat["outcome"],
            baseline.version_id if saved else None,
            state_key="assistant",
        )
    if chat["done"] and st.button("Yeni talep", icon=":material/refresh:"):
        chat["messages"] = []
        chat["pending"] = None
        chat["done"] = False
        chat["graph"] = build_order_graph(
            chat["active_baseline"],
            chat["client"],
            time_limit=st.session_state["time_limit"],
        )
        chat["config"] = {"configurable": {"thread_id": uuid4().hex}}
        st.rerun()

    confirming = bool(chat["pending"]) and chat["pending"]["kind"] == "confirmation"
    if text := st.chat_input(
        f"Örn. Yeni sipariş: {baseline.scenario.machines[0].name} üzerinde 30 dakika işlem",
        disabled=confirming,
    ):
        payload = Command(resume=text) if chat["pending"] else {"text": text}
        step(chat, baseline, payload, text)
        st.rerun()

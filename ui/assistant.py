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

# The team's evaluated model; any installed Gemma tag can be picked.
DEFAULT_MODEL = "gemma4:e2b"

CONNECTION_ERRORS = {
    "Local Ollama request failed": "Ollama çalışmıyor. Terminalde `ollama serve` ile başlatın.",
    "Model is not installed": "Bu model kurulu değil. `ollama pull {model}` ile indirin.",
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
    """Gemma chat models on the local Ollama, newest family first; empty when Ollama is not running."""
    try:
        tags = OllamaClient()._request("/api/tags").get("models", [])
    except ModelUnavailable:
        return []
    return sorted(
        tag["name"]
        for tag in tags
        if "gemma" in tag["name"].lower() and "embed" not in tag["name"].lower()
    )[::-1]


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
    chat["messages"].append(("user", said))
    with st.spinner("Gemma talebi okuyor…"):
        out = chat["graph"].invoke(payload, chat["config"])
    chat["audit"] = (out.get("session") or {}).get("audit", [])
    interrupts = out.get("__interrupt__")
    chat["pending"] = interrupts[0].value if interrupts else None
    if chat["pending"] and chat["pending"]["kind"] == "question":
        chat["messages"].append(
            ("assistant", "\n\n".join(chat["pending"]["questions"]))
        )
    elif chat["pending"]:
        chat["messages"].append(
            (
                "assistant",
                "Talebinizi aşağıdaki siparişe çevirdim. Kontrol edip onaylarsanız simüle ederim.",
            )
        )
    elif "explanation" in out:
        simulation = SimulationResult.model_validate(out["simulation"])
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


def model_cards(model, metadata, error):
    model_card, scope_card, search_card = st.columns(3)
    with model_card.container(border=True, height="stretch"):
        st.markdown("**:material/memory: Yerel model**")
        ui.gemma_status(metadata, error)
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

    models = installed_models()
    options = list(dict.fromkeys([DEFAULT_MODEL, *models]))
    model = st.selectbox(
        "Model",
        options,
        index=options.index(models[0]) if DEFAULT_MODEL not in models and models else 0,
        help="Yalnız bu bilgisayardaki Ollama'da kurulu Gemma modelleri listelenir.",
    )
    client, metadata, error = connect(model)
    model_cards(model, metadata, error)

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
    if chat["audit"] or chat["explanation"]:
        with st.expander("Model kaydı: hangi adımda hangi model ve istem sürümü"):
            ui.model_log(chat["audit"], chat["explanation"])
    if chat["outcome"]:
        st.divider()
        pages.simulation_result(
            baseline,
            chat["outcome"],
            baseline.version_id if saved else None,
            state_key="assistant",
        )
    if chat["done"] and st.button("Yeni talep", icon=":material/refresh:"):
        st.session_state.pop("assistant")
        st.rerun()

    confirming = bool(chat["pending"]) and chat["pending"]["kind"] == "confirmation"
    if text := st.chat_input(
        "Örn. Yeni sipariş: Torna 1 üzerinde 10 dakika tornalama",
        disabled=confirming or chat["done"],
    ):
        payload = Command(resume=text) if chat["pending"] else {"text": text}
        step(chat, baseline, payload, text)
        st.rerun()

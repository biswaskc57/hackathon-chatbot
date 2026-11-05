"""Streamlit chat UI for the Smart Tech support assistant (answers from the TV manual, BM25 search).

Run:  python3 run.py ui
Settings come from settings.json presets (config.py); the conversation logic is in assistant.py.
Changes in the sidebar apply from the next message and can be saved as a new preset.
"""

import json
import os
from dataclasses import replace

import streamlit as st

from assistant import LLMError, new_conversation_id, run_turn
from config import Settings, default_preset, list_presets, load_settings, save_preset
from llm_client import APIClient

OTHER_MODEL = "Other (type a name)…"

st.set_page_config(page_title="Smart Tech Support Assistant", page_icon="📺", layout="centered")


def model_options() -> list[str]:
    """Models from .env MODELS plus every model used in a preset."""
    names = [m.strip() for m in os.getenv("MODELS", "gpt-4o").split(",") if m.strip()]
    for p in list_presets():
        m = load_settings(p).model
        if m not in names:
            names.append(m)
    return names


# ---------- state ----------
def start_conversation() -> None:
    st.session_state.conversation_id = new_conversation_id()
    st.session_state.history = []
    st.session_state.display = [{"role": "assistant", "content": st.session_state.get("set_ai_disclosure")
                                 or load_settings().ai_disclosure, "meta": None}]
    st.session_state.stats = {"turns": 0, "input": 0, "output": 0, "total": 0, "latency": 0.0}


def apply_preset(name: str) -> None:
    """Copy a preset's values into the sidebar widgets."""
    s = load_settings(name)
    options = model_options()
    st.session_state.sel_preset = name
    st.session_state.set_model = s.model if s.model in options else OTHER_MODEL
    st.session_state.set_custom_model = "" if s.model in options else s.model
    st.session_state.set_temperature = float(s.temperature)
    st.session_state.set_max_tokens = int(s.max_tokens)
    st.session_state.set_history_turns = int(s.history_turns)
    st.session_state.set_system_prompt = s.system_prompt
    st.session_state.set_ai_disclosure = s.ai_disclosure
    st.session_state.set_extra_params = json.dumps(s.extra_params) if s.extra_params else ""
    st.session_state.loaded_fingerprint = s.fingerprint()


def on_preset_change() -> None:
    apply_preset(st.session_state.sel_preset)


def parse_extra_params() -> tuple[dict, str | None]:
    text = st.session_state.set_extra_params.strip()
    if not text:
        return {}, None
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        return {}, f"Extra parameters are not valid JSON: {exc.msg}"
    if not isinstance(value, dict):
        return {}, 'Extra parameters must be a JSON object, e.g. {"topP": 0.9}'
    return value, None


def current_settings() -> Settings:
    model = (st.session_state.set_custom_model.strip() if st.session_state.set_model == OTHER_MODEL
             else st.session_state.set_model)
    extra, _ = parse_extra_params()
    # Start from the preset, so settings without a sidebar widget (the search settings) keep the preset's value.
    s = replace(
        load_settings(st.session_state.sel_preset),
        model=model,
        temperature=float(st.session_state.set_temperature),
        max_tokens=int(st.session_state.set_max_tokens),
        history_turns=int(st.session_state.set_history_turns),
        system_prompt=st.session_state.set_system_prompt,
        ai_disclosure=st.session_state.set_ai_disclosure,
        extra_params=extra,
        preset=st.session_state.sel_preset,
    )
    if s.fingerprint() != st.session_state.get("loaded_fingerprint"):
        s.preset = f"{st.session_state.sel_preset} (edited)"
    return s


def on_save_preset() -> None:
    try:
        name = save_preset(st.session_state.new_preset_name, current_settings())
    except ValueError as exc:
        st.session_state.save_message = ("error", str(exc))
        return
    apply_preset(name)
    st.session_state.new_preset_name = ""
    st.session_state.save_message = ("success", f"Saved preset '{name}'.")


if "sel_preset" not in st.session_state:
    apply_preset(default_preset())
# Start fresh if any session key is missing (e.g. a browser tab left open from an older app version).
if any(k not in st.session_state for k in ("conversation_id", "history", "display", "stats")):
    start_conversation()


# ---------- sidebar: settings ----------
with st.sidebar:
    st.subheader("Settings preset")
    presets = list_presets()
    if st.session_state.sel_preset not in presets:
        apply_preset(default_preset())
    st.selectbox("Preset", presets, key="sel_preset", on_change=on_preset_change,
                 help="Presets live in settings.json. Changes below apply from the next message.")

    st.subheader("Model")
    st.selectbox("Model", model_options() + [OTHER_MODEL], key="set_model")
    if st.session_state.set_model == OTHER_MODEL:
        st.text_input("Model name", key="set_custom_model", placeholder="e.g. gpt-4.1")
    st.slider("Temperature", 0.0, 1.0, step=0.05, key="set_temperature",
              help="Lower = more consistent, factual answers. 0–0.2 is best for support.")
    st.number_input("Max answer length (tokens)", min_value=50, max_value=4000, step=50, key="set_max_tokens")
    st.slider("Conversation memory (turns)", 0, 20, key="set_history_turns",
              help="How many earlier question/answer pairs are resent. More = better context, more tokens. "
                   "0 = every message is answered on its own (used by the email-draft preset and the evaluation).")

    with st.expander("System prompt"):
        st.text_area("Instructions for the assistant", key="set_system_prompt", height=300)
        st.caption("The gateway accepts no system role, so this text is placed before the first user message.")
    with st.expander("AI disclosure (first message)"):
        st.text_area("Shown at the start of each new conversation", key="set_ai_disclosure", height=100)
    with st.expander("Advanced: extra gateway parameters"):
        st.text_area("JSON object", key="set_extra_params", placeholder='{"topP": 0.9}', height=80,
                     help="Sent as-is to the gateway, in its own parameter names (camelCase).")
        _, extra_error = parse_extra_params()
        if extra_error:
            st.error(extra_error)

    settings = current_settings()
    st.caption(f"Active: **{settings.preset}** · fingerprint `{settings.fingerprint()}`")

    col_a, col_b = st.columns(2)
    col_a.button("Reset to preset", on_click=on_preset_change, use_container_width=True)
    with col_b.popover("Save as preset", use_container_width=True):
        st.text_input("Preset name", key="new_preset_name", placeholder="e.g. strict-short")
        st.button("Save", on_click=on_save_preset, use_container_width=True)
    if "save_message" in st.session_state:
        kind, text = st.session_state.pop("save_message")
        (st.success if kind == "success" else st.error)(text)

    # ---------- sidebar: session ----------
    st.divider()
    st.subheader("Session")
    stats = st.session_state.stats
    st.markdown(f"**Conversation:** `{st.session_state.conversation_id}`")
    c1, c2 = st.columns(2)
    c1.metric("Turns", stats["turns"])
    c2.metric("Avg. response", f"{stats['latency'] / stats['turns']:.1f}s" if stats["turns"] else "–")
    c1.metric("Input tokens", stats["input"])
    c2.metric("Output tokens", stats["output"])
    st.metric("Total tokens", stats["total"])
    if st.button("New conversation", use_container_width=True):
        start_conversation()
        st.rerun()
    st.caption("EU-hosted gateway (Sweden Central). Answers use the 3 best manual passages (raw corpus). "
               "Turns are logged to logs/conversation_log.jsonl without customer text.")


# ---------- main ----------
st.title("📺 Smart Tech Support")
st.caption("Virtual assistant (AI) for Smart Tech TVs: settings and common problems.")

for msg in st.session_state.display:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg["meta"]:
            st.caption(msg["meta"])

user_text = st.chat_input("Describe your question or problem…")

if user_text:
    if not settings.model:
        st.error("Type a model name in the sidebar first.")
        st.stop()
    if parse_extra_params()[1]:
        st.error("Fix the extra gateway parameters in the sidebar first.")
        st.stop()

    with st.chat_message("user"):
        st.markdown(user_text)

    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            try:
                result = run_turn(APIClient(), st.session_state.history, user_text, settings,
                                  st.session_state.conversation_id, st.session_state.stats["turns"] + 1,
                                  source="ui")
            except LLMError as exc:
                st.error(f"The assistant could not answer: {exc}")
                st.stop()
        u = result.usage
        meta = (f"{settings.preset} · {settings.model} · temp {settings.temperature} · in {u['input_tokens']} · "
                f"out {u['output_tokens']} · total {u['total_tokens']} tokens · {result.latency_s:.1f}s")
        st.markdown(result.answer)
        st.caption(meta)

    st.session_state.history = result.history
    st.session_state.display += [
        {"role": "user", "content": user_text, "meta": None},
        {"role": "assistant", "content": result.answer, "meta": meta},
    ]
    stats = st.session_state.stats
    stats["turns"] += 1
    stats["input"] += u["input_tokens"] or 0
    stats["output"] += u["output_tokens"] or 0
    stats["total"] += u["total_tokens"] or 0
    stats["latency"] += result.latency_s
    st.rerun()
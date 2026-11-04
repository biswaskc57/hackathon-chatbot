"""Streamlit chat UI for the Smart Tech support assistant (early version, no RAG).

Run:  ./ui run   (or: python3 -m streamlit run app.py)
Uses llm_client.py for the gateway and the default system prompt from chat.py.
All model settings can be changed in the sidebar; changes apply from the next message.
"""

import json
import os
import time
import uuid
from datetime import datetime, timezone

import streamlit as st

from chat import AI_DISCLOSURE, SYSTEM_PROMPT, log_turn
from llm_client import APIClient, LLMError, parse_usage

# Models offered in the dropdown. Add more in .env, e.g. MODELS=gpt-4o,gpt-4.1
MODEL_OPTIONS = [m.strip() for m in os.getenv("MODELS", "gpt-4o").split(",") if m.strip()]
OTHER_MODEL = "Other (type a name)…"

DEFAULTS = {
    "set_model": os.getenv("MODEL", "gpt-4o") if os.getenv("MODEL", "gpt-4o") in MODEL_OPTIONS else MODEL_OPTIONS[0],
    "set_custom_model": "",
    "set_temperature": 0.2,
    "set_max_tokens": 600,
    "set_history_turns": 10,
    "set_system_prompt": SYSTEM_PROMPT,
    "set_extra_params": "",
    "set_show_meta": True,
}

st.set_page_config(page_title="Smart Tech Support Assistant", page_icon="📺", layout="centered")


# ---------- state ----------
def start_conversation() -> None:
    st.session_state.conversation_id = str(uuid.uuid4())[:8]
    st.session_state.history = []  # user/assistant messages only; system prompt is added per call
    st.session_state.display = [{"role": "assistant", "content": AI_DISCLOSURE, "meta": None}]
    st.session_state.stats = {"turns": 0, "input": 0, "output": 0, "total": 0, "latency": 0.0}


def reset_settings() -> None:
    for key, value in DEFAULTS.items():
        st.session_state[key] = value


# Start fresh if any session key is missing (e.g. a browser tab left open from an older app version).
if any(k not in st.session_state for k in ("conversation_id", "history", "display", "stats")):
    start_conversation()
for key, value in DEFAULTS.items():
    st.session_state.setdefault(key, value)


def get_client() -> APIClient:
    # Not cached on purpose: a cached client survives code reloads and keeps old behaviour.
    return APIClient()


def current_model() -> str:
    if st.session_state.set_model == OTHER_MODEL:
        return st.session_state.set_custom_model.strip()
    return st.session_state.set_model


def parse_extra_params() -> tuple[dict, str | None]:
    """Extra gateway parameters typed as JSON, e.g. {"topP": 0.9}."""
    text = st.session_state.set_extra_params.strip()
    if not text:
        return {}, None
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        return {}, f"Extra parameters are not valid JSON: {exc.msg}"
    if not isinstance(value, dict):
        return {}, "Extra parameters must be a JSON object, e.g. {\"topP\": 0.9}"
    return value, None


# ---------- sidebar: settings ----------
with st.sidebar:
    st.subheader("Model settings")

    st.selectbox(
        "Model",
        MODEL_OPTIONS + [OTHER_MODEL],
        key="set_model",
        help="Models the gateway accepts. Add more with MODELS=... in .env.",
    )
    if st.session_state.set_model == OTHER_MODEL:
        st.text_input("Model name", key="set_custom_model", placeholder="e.g. gpt-4.1")

    st.slider(
        "Temperature",
        0.0, 1.0, step=0.05, key="set_temperature",
        help="Lower = more consistent, factual answers. 0–0.2 is best for support.",
    )
    st.number_input(
        "Max answer length (tokens)",
        min_value=50, max_value=4000, step=50, key="set_max_tokens",
        help="Upper limit for one answer. Sent to the gateway as maxTokens.",
    )
    st.slider(
        "Conversation memory (turns)",
        1, 20, key="set_history_turns",
        help="How many previous question/answer pairs are resent. More = better context, more tokens.",
    )

    with st.expander("System prompt"):
        st.text_area("Instructions for the assistant", key="set_system_prompt", height=300)
        st.caption("The gateway accepts no system role, so this text is placed before the first user message.")

    with st.expander("Advanced: extra gateway parameters"):
        st.text_area(
            "JSON object",
            key="set_extra_params",
            placeholder='{"topP": 0.9}',
            height=80,
            help="Sent as-is to the gateway. Use the gateway's own parameter names (camelCase).",
        )
        _, extra_error = parse_extra_params()
        if extra_error:
            st.error(extra_error)

    st.toggle("Show tokens and timing under answers", key="set_show_meta")
    st.button("Reset settings", on_click=reset_settings, use_container_width=True)

    # ---------- sidebar: session ----------
    st.divider()
    st.subheader("Session")
    stats = st.session_state.stats
    st.markdown(f"**Conversation:** `{st.session_state.conversation_id}`")
    col1, col2 = st.columns(2)
    col1.metric("Turns", stats["turns"])
    col2.metric("Avg. response", f"{stats['latency'] / stats['turns']:.1f}s" if stats["turns"] else "–")
    col1.metric("Input tokens", stats["input"])
    col2.metric("Output tokens", stats["output"])
    st.metric("Total tokens", stats["total"])

    if st.button("New conversation", use_container_width=True):
        start_conversation()
        st.rerun()

    st.caption(
        "AI assistant on an EU-hosted gateway (Sweden Central). Early version: no manual "
        "retrieval yet. Turns are logged to logs/conversation_log.jsonl without customer text."
    )


# ---------- main ----------
st.title("📺 Smart Tech Support")
st.caption("Virtual assistant (AI) for Smart Tech TVs: settings and common problems.")

for msg in st.session_state.display:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg["meta"] and st.session_state.set_show_meta:
            st.caption(msg["meta"])

user_text = st.chat_input("Describe your question or problem…")

if user_text:
    model = current_model()
    extra_params, extra_error = parse_extra_params()
    if not model:
        st.error("Type a model name in the sidebar first.")
        st.stop()
    if extra_error:
        st.error(extra_error)
        st.stop()

    st.session_state.display.append({"role": "user", "content": user_text, "meta": None})
    with st.chat_message("user"):
        st.markdown(user_text)

    turns = st.session_state.set_history_turns
    history = (st.session_state.history + [{"role": "user", "content": user_text}])[-(2 * turns + 1):]
    messages = [{"role": "system", "content": st.session_state.set_system_prompt}] + history

    settings = {
        "temperature": st.session_state.set_temperature,
        "maxTokens": int(st.session_state.set_max_tokens),
        **extra_params,
    }

    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            start = time.perf_counter()
            try:
                response = get_client().create_chat_completion(model=model, messages=messages, **settings)
            except LLMError as exc:
                st.session_state.display.pop()  # forget the unanswered question
                st.error(f"The assistant could not answer: {exc}")
                st.stop()
            latency = time.perf_counter() - start

        answer = response["data"]["content"]
        usage = parse_usage(response)
        meta = (
            f"{model} · temp {settings['temperature']} · in {usage['input_tokens']} · "
            f"out {usage['output_tokens']} · total {usage['total_tokens']} tokens · {latency:.1f}s"
        )
        st.markdown(answer)
        if st.session_state.set_show_meta:
            st.caption(meta)

    # update state
    st.session_state.history = history + [{"role": "assistant", "content": answer}]
    st.session_state.display.append({"role": "assistant", "content": answer, "meta": meta})

    stats = st.session_state.stats
    stats["turns"] += 1
    stats["input"] += usage["input_tokens"] or 0
    stats["output"] += usage["output_tokens"] or 0
    stats["total"] += usage["total_tokens"] or 0
    stats["latency"] += latency

    log_turn({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "conversation_id": st.session_state.conversation_id,
        "turn": stats["turns"],
        "model": model,
        "temperature": settings["temperature"],
        "max_tokens": settings["maxTokens"],
        "history_turns": turns,
        "system_prompt_changed": st.session_state.set_system_prompt != SYSTEM_PROMPT,
        "extra_params": extra_params,
        "user_chars": len(user_text),
        "answer_chars": len(answer),
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "total_tokens": usage["total_tokens"],
        "latency_s": round(latency, 2),
        "source": "ui",
    })
    st.rerun()
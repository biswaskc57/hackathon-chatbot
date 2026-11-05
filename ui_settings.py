"""Settings panel for the Streamlit pages: preset, model, temperature, prompt, extra parameters.

Moved unchanged from the first app.py so the demo page can show it inside a sidebar expander.
Changes apply from the next message and can be saved as a new preset (settings.json).
"""

import json
import os
from dataclasses import replace

import streamlit as st

from config import Settings, default_preset, list_presets, load_settings, save_preset

OTHER_MODEL = "Other (type a name)…"


def model_options() -> list[str]:
    """Models from .env MODELS plus every model used in a preset."""
    names = [m.strip() for m in os.getenv("MODELS", "gpt-4o").split(",") if m.strip()]
    for p in list_presets():
        m = load_settings(p).model
        if m not in names:
            names.append(m)
    return names


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
    # Start from the preset, so settings without a sidebar widget (search, tickets) keep the preset's value.
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


def init(preferred: str | None = None) -> None:
    """Load a preset into the widgets once per session (preferred if it exists, else the default preset)."""
    if "sel_preset" not in st.session_state:
        presets = list_presets()
        apply_preset(preferred if preferred in presets else default_preset())
    # Streamlit drops a widget's value when the widget is not drawn in a run (presenter mode hides the panel).
    # Writing the values back each run keeps them.
    for key in WIDGET_KEYS:
        if key in st.session_state:
            st.session_state[key] = st.session_state[key]


WIDGET_KEYS = ("sel_preset", "set_model", "set_custom_model", "set_temperature", "set_max_tokens",
               "set_history_turns", "set_system_prompt", "set_ai_disclosure", "set_extra_params")


def render_panel() -> Settings:
    """The settings widgets. Call inside st.sidebar (or an expander there). Returns the active settings."""
    presets = list_presets()
    if st.session_state.sel_preset not in presets:
        apply_preset(default_preset())
    st.selectbox("Preset", presets, key="sel_preset", on_change=on_preset_change,
                 help="Presets live in settings.json. Changes below apply from the next message.")

    st.selectbox("Model", model_options() + [OTHER_MODEL], key="set_model")
    if st.session_state.set_model == OTHER_MODEL:
        st.text_input("Model name", key="set_custom_model", placeholder="e.g. gpt-4.1")
    st.slider("Temperature", 0.0, 1.0, step=0.05, key="set_temperature",
              help="Lower = more consistent, factual answers. 0–0.2 is best for support.")
    st.number_input("Max answer length (tokens)", min_value=50, max_value=4000, step=50, key="set_max_tokens")
    st.slider("Conversation memory (turns)", 0, 20, key="set_history_turns",
              help="How many earlier question/answer pairs are resent. More = better context, more tokens. "
                   "0 = every message is answered on its own (used by the email-draft preset and the evaluation).")

    st.text_area("System prompt", key="set_system_prompt", height=200,
                 help="The gateway accepts no system role, so this text is placed before the first user message.")
    st.text_area("AI disclosure (first message)", key="set_ai_disclosure", height=90)
    st.text_area("Extra gateway parameters (JSON)", key="set_extra_params", placeholder='{"topP": 0.9}', height=68,
                 help="Sent as-is to the gateway, in its own parameter names (camelCase).")
    _, extra_error = parse_extra_params()
    if extra_error:
        st.error(extra_error)

    settings = current_settings()
    st.caption(f"Active: **{settings.preset}** · fingerprint `{settings.fingerprint()}` · "
               f"search {settings.search_label()} · tickets {'on' if settings.tickets else 'off'}")
    col_a, col_b = st.columns(2)
    col_a.button("Reset to preset", on_click=on_preset_change, use_container_width=True)
    with col_b.popover("Save as preset", use_container_width=True):
        st.text_input("Preset name", key="new_preset_name", placeholder="e.g. strict-short")
        st.button("Save", on_click=on_save_preset, use_container_width=True)
    if "save_message" in st.session_state:
        kind, text = st.session_state.pop("save_message")
        (st.success if kind == "success" else st.error)(text)
    return settings

"""Shared pieces for the demo pages: styles, source chips, the "Why this answer" strip, scenarios and replays."""

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

from retrieval import load_corpus

ROOT = Path(__file__).resolve().parent
SCENARIOS_FILE = ROOT / "demo" / "scenarios.json"
REPLAYS = ROOT / "demo" / "replays"
CITATION = re.compile(r"\[?(p\d{4})\]?")

ACCENT = "#1f5fbf"
STATUS_STYLE = {   # colour only for meaning
    "passed": ("#1e7d3a", "#e6f4ea", "passed"),
    "handed_over": ("#9a6700", "#fff4d6", "handed over"),
    "blocked": ("#b42318", "#fde8e7", "blocked"),
    "off": ("#667085", "#f2f4f7", "off"),
}


# ---------- styles ----------
def inject_css(presenter: bool) -> None:
    base = 22 if presenter else 18
    st.markdown(f"""<style>
    html, body, [data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li {{ font-size: {base}px; }}
    [data-testid="stChatMessage"] {{ padding: 0.6rem 0.9rem; border-radius: 12px; }}
    .block-container {{ padding-top: 2.2rem; padding-bottom: 0.5rem; }}
    .st-notice {{ background: {ACCENT}; color: #fff; padding: 0.45rem 0.9rem; border-radius: 8px;
                  font-weight: 600; font-size: {base - 2}px; margin-bottom: 0.6rem; }}
    .st-pane-title {{ font-size: {base + 4}px; font-weight: 700; margin: 0 0 0.3rem 0; }}
    .st-chip {{ display: inline-block; border: 1px solid {ACCENT}; color: {ACCENT}; border-radius: 999px;
               padding: 0 0.55rem; margin: 0.15rem 0.25rem 0 0; font-size: {base - 5}px; cursor: help; }}
    .st-trace {{ display: flex; gap: 0.5rem; flex-wrap: wrap; }}
    .st-step {{ flex: 1 1 180px; border-radius: 10px; padding: 0.5rem 0.7rem; border-left: 6px solid; color: #101828; }}
    .st-step b {{ font-size: {base - 2}px; }}
    .st-step .st-status {{ font-size: {base - 5}px; font-weight: 700; text-transform: uppercase; }}
    .st-step .st-reason {{ font-size: {base - 5}px; color: #333; }}
    .st-ticket {{ border: 1px solid #d0d5dd; border-radius: 10px; padding: 0.5rem 0.8rem; margin-bottom: 0.4rem; }}
    </style>""", unsafe_allow_html=True)


# ---------- passages and source chips ----------
@st.cache_resource
def passages() -> dict:
    return {p.id: p for p in load_corpus()}


def cited_ids(answer: str) -> list[str]:
    known = passages()
    return [i for i in dict.fromkeys(CITATION.findall(answer)) if i in known]


def chips_html(ids: list[str]) -> str:
    """Small chips; hovering shows the passage text."""
    out = []
    for pid in ids:
        p = passages().get(pid)
        if p:
            out.append(f'<span class="st-chip" title="{html.escape(p.text[:900])}">{pid} · {html.escape(p.title)}</span>')
    return "".join(out)


def render_sources(ids: list[str], key: str) -> None:
    if not ids:
        return
    st.markdown("Sources: " + chips_html(ids), unsafe_allow_html=True)
    with st.expander("Show source text", expanded=False):
        for pid in ids:
            p = passages().get(pid)
            if p:
                st.markdown(f"**{pid} · {p.title}**")
                st.caption(p.text)


# ---------- "Why this answer" strip ----------
def render_trace(trace: list[dict] | None, replay_file: str | None = None) -> None:
    title = "Why this answer" + (" · replay" if replay_file else "")
    with st.expander(title, expanded=True):
        if not trace:
            st.caption("Send a message to see how the answer was made.")
            return
        cards = []
        for step in trace:
            fg, bg, label = STATUS_STYLE.get(step["status"], STATUS_STYLE["off"])
            cards.append(f'<div class="st-step" style="background:{bg}; border-color:{fg}">'
                         f'<b>{html.escape(step["name"])}</b><br>'
                         f'<span class="st-status" style="color:{fg}">{label}</span><br>'
                         f'<span class="st-reason">{html.escape(step["reason"])}</span></div>')
        st.markdown(f'<div class="st-trace">{"".join(cards)}</div>', unsafe_allow_html=True)
        if replay_file:
            st.caption(f"Replayed from {replay_file} (recorded with the live gateway).")


# ---------- scenarios ----------
def load_scenarios() -> list[dict]:
    with SCENARIOS_FILE.open(encoding="utf-8") as f:
        return json.load(f)["scenarios"]


def scenario_ready(scenario: dict, settings) -> bool:
    """A scenario is enabled once every setting it needs exists and is on in the active preset."""
    return all(getattr(settings, name, False) for name in scenario.get("requires", []))


# ---------- replays ----------
def replay_path(scenario_id: str) -> Path:
    return REPLAYS / f"scenario_{scenario_id}.json"


def save_replay(scenario: dict, result, settings) -> Path:
    REPLAYS.mkdir(parents=True, exist_ok=True)
    path = replay_path(scenario["id"])
    path.write_text(json.dumps({
        "scenario": scenario["id"], "label": scenario["label"], "message": scenario["message"],
        "answer": result.answer, "retrieved_ids": result.retrieved_ids, "route": result.route,
        "route_category": result.route_category, "handover_reason": result.handover_reason,
        "masked_message": result.history[-2]["content"] if len(result.history) >= 2 else scenario["message"],
        "trace": [vars(s) for s in result.trace], "usage": {k: v for k, v in result.usage.items() if k != "raw_usage"},
        "preset": settings.preset, "settings_fingerprint": settings.fingerprint(), "model": settings.model,
        "recorded": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def load_replay(scenario_id: str) -> dict | None:
    path = replay_path(scenario_id)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

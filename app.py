"""Live demo page (R8): customer chat on the left, agent console on the right, "Why this answer" at the bottom.

Run:  python3 run.py ui        (designed for a projector at 1920x1080; the e-mail page is in the sidebar)
Everything goes through assistant.run_turn(), the same engine as the CLI, the API and the evaluation.
Settings come from settings.json presets; the page starts with the "demo" preset (baseline + tickets).
No cost or business numbers on screen: they are in the separate presentation.
"""

import streamlit as st

import tickets
import ui_settings
from assistant import LLMError, TraceStep, TurnResult, new_conversation_id, run_turn
from config import load_settings
from llm_client import APIClient
from ui_components import (cited_ids, inject_css, load_replay, load_scenarios, passages, render_sources,
                           render_trace, save_replay, scenario_ready)

SOURCE = "demo"   # log source and ticket source; Reset demo clears the tickets of this source

st.set_page_config(page_title="Smart Tech Support · Live demo", page_icon="📺", layout="wide",
                   initial_sidebar_state="collapsed" if st.session_state.get("presenter") else "expanded")
ss = st.session_state


# ---------- state ----------
def start_conversation() -> None:
    ss.conversation_id = new_conversation_id()
    ss.history = []
    ss.display = [{"role": "assistant", "content": ss.get("set_ai_disclosure") or load_settings().ai_disclosure}]
    ss.turn = 0
    ss.last_trace = None
    ss.last_replay = None
    ss.ticket_id = None


ui_settings.init(preferred="demo")
if any(k not in ss for k in ("conversation_id", "history", "display", "turn")):
    start_conversation()
ss.setdefault("presenter", False)
ss.setdefault("replay_mode", False)
ss.setdefault("record", False)
ss.setdefault("suggestions", {})


def reset_demo() -> None:
    start_conversation()
    tickets.clear(SOURCE)
    ss.suggestions = {}


# ---------- sidebar ----------
with st.sidebar:
    st.markdown("### 📺 Smart Tech · demo")
    st.toggle("Presenter mode", key="presenter", help="Larger fonts; hides settings and debug output.")
    inject_css(ss.presenter)

    settings = ui_settings.current_settings()   # widget values from the last run; the panel itself is at the bottom
    st.markdown("**Demo scenarios**")
    pending = None
    for sc in load_scenarios():
        ready = scenario_ready(sc, settings)
        label = f"{sc['id']} · {sc['label']}" + ("" if ready else " (coming soon)")
        if st.button(label, key=f"scenario_{sc['id']}", disabled=not ready, use_container_width=True,
                     help=None if ready else "Needs: " + ", ".join(sc["requires"]) + " (not built or switched off yet)"):
            pending = sc
    st.divider()
    st.toggle("Replay mode", key="replay_mode",
              help="Scenarios play from demo/replays/ instead of calling the gateway. Use if the network fails.")
    if not ss.presenter:
        st.toggle("Record scenarios", key="record", help="Save each live scenario run to demo/replays/.")
    st.button("Reset demo", on_click=reset_demo, use_container_width=True,
              help="Clears the chat, the trace and the demo tickets.")
    if not ss.presenter:
        with st.expander("Settings", expanded=False):
            settings = ui_settings.render_panel()
        st.caption(f"Conversation `{ss.conversation_id}` · preset **{settings.preset}** "
                   f"(`{settings.fingerprint()}`) · {settings.model}")


# ---------- one turn ----------
def turn_settings(sc: dict | None):
    """A scenario may run with its own preset (scenario 4: the stress test with the manual switched off)."""
    return load_settings(sc["preset"]) if sc and sc.get("preset") else settings


def replay_turn(sc: dict, message: str) -> TurnResult | None:
    data = load_replay(sc["id"]) if sc else None
    if not data:
        return None
    result = TurnResult(answer=data["answer"], history=ss.history + [{"role": "user", "content": message},
                                                                     {"role": "assistant", "content": data["answer"]}],
                        usage=data.get("usage", {}), latency_s=0.0, retrieved_ids=data["retrieved_ids"],
                        trace=[TraceStep(**s) for s in data["trace"]], route=data.get("route", "answer"),
                        route_category=data.get("route_category", ""), handover_reason=data.get("handover_reason", ""))
    s_turn = turn_settings(sc)
    if s_turn.tickets:
        found = [passages()[i] for i in data["retrieved_ids"] or [] if i in passages()]
        masked = data.get("masked_message", message)   # the ticket stores the masked text, as in a live run
        result.ticket_id = tickets.record_turn(ss.conversation_id, SOURCE, masked, result, found, s_turn)
    return result


def send(message: str, sc: dict | None = None) -> None:
    result, replay_file = None, None
    if sc and ss.replay_mode:
        result = replay_turn(sc, message)
        replay_file = f"demo/replays/scenario_{sc['id']}.json" if result else None
        if result is None:
            st.toast("No recording for this scenario yet: using the live gateway.")
    if result is None:
        try:
            result = run_turn(APIClient(), ss.history, message, turn_settings(sc), ss.conversation_id,
                              ss.turn + 1, source=SOURCE)
        except LLMError as exc:
            result = replay_turn(sc, message) if sc else None   # fallback when the gateway or network fails
            if result is None:
                st.error(f"The assistant could not answer: {exc}")
                return
            replay_file = f"demo/replays/scenario_{sc['id']}.json"
            st.toast("Gateway unavailable: replaying the recorded answer.")
        else:
            if sc and ss.record:
                st.toast(f"Recorded {save_replay(sc, result, turn_settings(sc)).name}")
    ss.turn += 1
    ss.history = result.history
    ss.ticket_id = result.ticket_id or ss.ticket_id
    ss.last_trace = [vars(s) for s in result.trace]
    ss.last_replay = replay_file
    u = result.usage
    ss.display += [
        {"role": "user", "content": message},
        {"role": "assistant", "content": result.answer, "sources": cited_ids(result.answer), "turn": ss.turn,
         "note": sc.get("note") if sc else None,
         "meta": f"{u.get('input_tokens')} in · {u.get('output_tokens')} out tokens · {result.latency_s:.1f}s"
                 + (" · replay" if replay_file else "")},
    ]


if pending:
    if pending["page"] == "email":
        ss.preload_email = dict(pending["email"], id=f"S{pending['id']}", label=pending["label"])
        st.switch_page("pages/1_Agent_inbox.py")
    start_conversation()   # each scenario starts a fresh conversation, so live and replay give the same turn
    with st.spinner("Searching the manual and answering…"):
        send(pending["message"], pending)
    st.rerun()


# ---------- customer (left) and agent console (right) ----------
left, right = st.columns([3, 2], gap="large")

with left:
    st.markdown('<div class="st-pane-title">Customer</div>', unsafe_allow_html=True)
    st.markdown('<div class="st-notice">You\'re chatting with an AI assistant</div>', unsafe_allow_html=True)
    chat = st.container(height=400 if ss.presenter else 460, border=False)   # leaves room for the trace strip at 1080p
    with chat:
        for i, msg in enumerate(ss.display):
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                if msg["role"] == "assistant" and msg.get("sources"):
                    render_sources(msg["sources"], key=f"src_{i}")
                if msg.get("note"):
                    st.caption("🧪 " + msg["note"])
                if msg.get("meta") and not ss.presenter:
                    st.caption(msg["meta"])

        last = ss.display[-1]
        if last["role"] == "assistant" and last.get("turn"):
            t = tickets.get(ss.ticket_id) if ss.ticket_id else None
            if t and t["status"] in ("RESOLVED_BY_BOT", "HANDED_OVER"):
                st.caption("Thanks, solved." if t["status"] == "RESOLVED_BY_BOT"
                           else "A colleague will take over. Your conversation was passed on with a summary.")
            else:
                st.caption("Did this help?")
                a, b, c, _ = st.columns([1, 1, 2, 3])
                if a.button("👍 Yes", key=f"yes_{last['turn']}"):
                    if ss.ticket_id:
                        tickets.set_feedback(ss.ticket_id, True)
                    st.rerun()
                if b.button("👎 No", key=f"no_{last['turn']}"):
                    if ss.ticket_id:
                        tickets.set_feedback(ss.ticket_id, False)
                    st.toast("Sorry about that. You can describe the problem again or ask for a person.")
                if c.button("Talk to a person", key=f"human_{last['turn']}"):
                    if ss.ticket_id:
                        tickets.hand_over(ss.ticket_id, "Customer asked for a person")
                    st.rerun()
                if not settings.tickets and not ss.presenter:
                    st.caption("Tickets are off in this preset: feedback is not stored.")

    message = st.chat_input("Describe your question or problem…")
    if message:
        with st.spinner("Searching the manual and answering…"):
            send(message)
        st.rerun()


@st.fragment(run_every="2s")
def agent_console() -> None:
    st.markdown('<div class="st-pane-title">Agent console</div>', unsafe_allow_html=True)
    waiting = tickets.queue()
    if not waiting:
        st.info("No handed-over tickets. Hand-overs from the chat appear here.")
        return
    labels = {t["ticket_id"]: f"{t['ticket_id']} · {t['subject']} · {t['category'] or '–'} · {t['priority']}"
              for t in waiting}
    tid = st.radio("Queue", list(labels), format_func=labels.get, key="agent_selected")
    t = tickets.get(tid)
    if not t:
        return
    with st.container(border=True):
        st.markdown(f"**{t['subject']}**  \n{t['category'] or 'No category'} · priority {t['priority']} · "
                    f"{t['turns']} bot turn(s)")
        st.markdown(f"**Hand-over reason:** {t['handover_reason'] or '–'}")
        st.markdown("**Summary (masked)**")
        st.text(t["summary"])
        st.markdown("**Steps tried by the bot:** " + ("; ".join(t["steps_tried"]) or "none"))
        render_sources(t["source_passage_ids"], key=f"agent_src_{tid}")

    if st.button("✨ Suggest reply", key=f"suggest_{tid}"):
        from email_draft import draft_reply   # agent assist: the e-mail drafter on the masked summary
        with st.spinner("Drafting from the manual…"):
            d = draft_reply(t["subject"], t["summary"])
        ss.suggestions[tid] = d.draft or ("No suggestion: " + (d.triage_note or d.notes_for_agent or "not covered"))
    if tid in ss.suggestions:
        st.text_area("Suggested reply (agent assist)", ss.suggestions[tid], height=220, key=f"sugg_{tid}")
    a, b = st.columns(2)
    if a.button("Resolved by agent", key=f"resolve_{tid}", use_container_width=True):
        tickets.update(tid, status="RESOLVED_BY_AGENT")
        st.rerun()
    if b.button("Escalate to tier 2", key=f"tier2_{tid}", use_container_width=True):
        tickets.update(tid, status="TIER2")
        st.rerun()


with right:
    agent_console()

render_trace(ss.last_trace, ss.last_replay)

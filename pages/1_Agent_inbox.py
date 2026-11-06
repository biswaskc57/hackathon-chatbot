"""Agent inbox: an e-mail comes in, the assistant drafts a reply from the manual, the agent reviews,
edits and sends it (sending is simulated).

Opens as a second page next to the chat (python3 run.py ui, then "Agent inbox" in the sidebar).
The drafting itself is email_draft.py (preset "email-draft"). Each send or discard is logged to
logs/email_review_log.jsonl WITHOUT customer text: decision, effort level, how much the agent changed,
seconds from draft to send. That is the evidence for the "minutes saved per draft" assumption.
"""

import csv
import difflib
import json
import os
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

from email_draft import AI_NOTICE, DEMO_FILE, clean_email, draft_reply, email_settings
from retrieval import load_corpus

ROOT = Path(__file__).resolve().parent.parent
REVIEW_LOG = Path(os.getenv("EMAIL_REVIEW_LOG", ROOT / "logs" / "email_review_log.jsonl"))
CATEGORIES = ["Picture & Sound", "Network, Apps & Software", "Connected Devices & Remote", "Power, Setup & Viewing", "Out of scope"]
TYPES = ["how-to", "troubleshooting", "out of scope"]
PRIORITIES = ["high", "medium", "low"]
EFFORT = ["Sent as-is", "Minor edit", "Major edit", "Discarded"]

st.set_page_config(page_title="Agent inbox · Smart Tech", page_icon="📨", layout="wide")


@st.cache_data
def demo_emails() -> list[dict]:
    return [json.loads(line) for line in DEMO_FILE.open(encoding="utf-8") if line.strip()]


@st.cache_data
def ticket_emails() -> list[dict]:
    """E-mail and web-form tickets from the organisers' blind set: for showing only, never for tuning."""
    with open(ROOT / "data" / "tickets_tv.csv", encoding="utf-8") as f:
        return [{"id": r["ticket_id"], "subject": r["subject"], "body": r["body"], "origin": "ticket",
                 "what_it_tests": f"{r['channel']} ticket from tickets_tv.csv"}
                for r in csv.DictReader(f) if r["channel"] in ("email", "web-form")]


@st.cache_resource
def passages() -> dict:
    return {p.id: p for p in load_corpus()}


def suggest_effort(draft: str, final: str) -> str:
    """A first guess from how much text changed; the agent confirms or corrects it."""
    ratio = difflib.SequenceMatcher(None, draft, final).ratio()
    return EFFORT[0] if ratio >= 0.98 else EFFORT[1] if ratio >= 0.80 else EFFORT[2]


def log_review(record: dict) -> None:
    REVIEW_LOG.parent.mkdir(parents=True, exist_ok=True)
    with REVIEW_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------- state ----------
ss = st.session_state
ss.setdefault("inbox", [dict(e, origin="demo") for e in demo_emails()])
ss.setdefault("drafts", {})      # email id -> EmailDraft as dict
ss.setdefault("shown_at", {})    # email id -> time the draft appeared
ss.setdefault("done", {})        # email id -> outcome record


def add_to_inbox(email: dict) -> None:
    """Add (or replace) an e-mail and select it."""
    ss.inbox = [e for e in ss.inbox if e["id"] != email["id"]] + [email]
    ss.drafts.pop(email["id"], None)
    ss.done.pop(email["id"], None)
    ss.selected = email["id"]


# Demo scenario 6 on the live demo page sends its e-mail here.
if "preload_email" in ss:
    pre = ss.pop("preload_email")
    add_to_inbox({"id": pre["id"], "subject": pre["subject"], "body": pre["body"], "origin": "scenario",
                  "what_it_tests": f"demo scenario: {pre['label']}"})

def status(eid: str) -> str:
    return "✅" if eid in ss.done else "📝" if eid in ss.drafts else "✉️"


# ---------- sidebar: inbox ----------
with st.sidebar:
    st.subheader("📨 Inbox")
    # Labels must not change between runs (a changing label resets the selection), so the status is shown separately.
    subjects = {e["id"]: e["subject"] for e in ss.inbox}
    selected = st.radio("E-mails", list(subjects), format_func=lambda i: f"{i} · {subjects[i]}",
                        key="selected", label_visibility="collapsed")
    st.caption("  ".join(f"{i} {status(i)}" for i in subjects))
    with st.expander("📥 Load from tickets (e-mail / web form)"):
        options = {t["id"]: t for t in ticket_emails()}
        pick = st.selectbox("Ticket", list(options), format_func=lambda i: f"{i} · {options[i]['subject']}",
                            key="ticket_pick")
        if st.button("Load into inbox", key="load_ticket"):
            add_to_inbox(options[pick])
            st.rerun()
    with st.expander("➕ New e-mail"):
        with st.form("new_email", clear_on_submit=True):
            subj = st.text_input("Subject")
            body = st.text_area("Body", height=160)
            if st.form_submit_button("Add to inbox") and subj.strip() and body.strip():
                new_id = f"N{sum(e['origin'] == 'pasted' for e in ss.inbox) + 1}"
                ss.inbox.append({"id": new_id, "subject": subj.strip(), "body": body.strip(), "origin": "pasted",
                                 "what_it_tests": "pasted by the agent"})
                st.rerun()
    st.divider()
    handled = list(ss.done.values())
    st.caption(f"Handled: {len(handled)} of {len(ss.inbox)}")
    for level in EFFORT:
        n = sum(r["effort"] == level for r in handled)
        if n:
            st.caption(f"{level}: {n}")
    settings = email_settings()
    st.caption(f"Preset **{settings.preset}** · fingerprint `{settings.fingerprint()}` · "
               f"search {settings.search_label()}, top {settings.top_k}. Demo e-mails are written by the team, not tickets.")

email = next(e for e in ss.inbox if e["id"] == selected)
eid = email["id"]

st.title("Agent inbox")
st.caption("The assistant drafts from the TV manual. You review, edit and send. Nothing is sent to customers: sending is simulated.")

left, right = st.columns([2, 3], gap="large")

# ---------- left: the e-mail as received ----------
with left:
    st.markdown(f"#### {status(eid)} {email['subject']}")
    st.text(email["body"])
    if email.get("origin") in ("demo", "scenario", "ticket"):
        st.caption(f"{eid}: {email['what_it_tests']}")
    masked, removed = clean_email(email["body"])
    with st.expander("🔒 What the assistant sees (masked)", expanded=email.get("origin") == "scenario"):
        st.text(f"Subject: {email['subject']}\n\n{masked}")
        st.caption("Removed or masked: " + ("; ".join(removed) if removed else "nothing found"))
    d = ss.drafts.get(eid)
    if d and d["removed_before_model"]:
        st.caption("Removed before the assistant saw it: " + "; ".join(d["removed_before_model"]))
    if eid not in ss.drafts and eid not in ss.done:
        if st.button("✨ Create draft", type="primary", key=f"create_{eid}"):
            with st.spinner("Searching the manual and drafting…"):
                ss.drafts[eid] = asdict(draft_reply(email["subject"], email["body"]))
                ss.shown_at[eid] = time.time()
            st.rerun()

# ---------- right: draft, checks, sources, send ----------
with right:
    d = ss.drafts.get(eid)
    if eid in ss.done:
        r = ss.done[eid]
        took = f"{r['seconds_to_send']} s from draft to send · " if r["seconds_to_send"] is not None else ""
        st.success(f"Handled: **{r['effort']}** · {took}"
                   f"text kept from the draft: {round(100 * r['similarity'])}%")
        if r.get("final_text"):
            st.text_area("Sent e-mail (simulated)", r["final_text"], height=300, disabled=True, key=f"sent_{eid}")
    elif not d:
        st.info("No draft yet. Press **Create draft**.")
    else:
        st.caption("Decision for the whole e-mail. Detected questions with a decision each come with the "
                   "R7 question split (coming soon).")
        verdict = {"draft": ("success", "Draft ready: review before sending."),
                   "partial": ("info", "Partial draft: the TV part is answered, the rest is handed over (see triage note)."),
                   "no_draft": ("warning", "No draft: the assistant did not find a reliable answer in the manual.")}
        kind, text = verdict.get(d["decision"], ("warning", f"Decision: {d['decision']}"))
        getattr(st, kind)(text)
        for w in d["warnings"]:
            st.warning("⚠️ " + w)
        if d["triage_note"]:
            st.info("**Triage note:** " + d["triage_note"])
        if d["notes_for_agent"]:
            st.caption("**Note for agent:** " + d["notes_for_agent"])

        c1, c2, c3 = st.columns(3)
        c1.selectbox("Category", CATEGORIES, index=CATEGORIES.index(d["category"]) if d["category"] in CATEGORIES else 0, key=f"cat_{eid}")
        c2.selectbox("Type", TYPES, index=TYPES.index(d["type"]) if d["type"] in TYPES else 0, key=f"type_{eid}")
        c3.selectbox("Priority", PRIORITIES, index=PRIORITIES.index(d["priority"]) if d["priority"] in PRIORITIES else 1, key=f"prio_{eid}")

        subject = st.text_input("Subject", d["subject"] or f"Re: {email['subject']}", key=f"subj_{eid}")
        final = st.text_area("Edit the reply before approving", d["draft"], height=320, key=f"text_{eid}",
                             placeholder="No draft. Write the reply yourself, or forward the e-mail as the triage note says.")

        with st.expander(f"📚 Manual passages used ({len(d['retrieved_ids'])} found, {len(d['cited_ids'])} cited)"):
            for pid in d["retrieved_ids"]:
                p = passages().get(pid)
                if p:
                    mark = "✅ cited" if pid in d["cited_ids"] else "not cited"
                    st.markdown(f"**{pid} · {p.title}** · {mark}")
                    st.caption(p.text)

        suggested = suggest_effort(d["draft"], final) if d["draft"] else EFFORT[2]
        kept = difflib.SequenceMatcher(None, d["draft"], final).ratio() if d["draft"] else 0.0
        # The key includes the suggestion: when an edit changes the suggestion, the choice follows it;
        # otherwise the agent's own choice is kept.
        effort = st.radio("How much did you change?", EFFORT[:3], horizontal=True, key=f"effort_{eid}_{suggested}",
                          index=EFFORT.index(suggested),
                          help="Suggested from how much text changed; correct it if needed.")
        st.caption(f"Suggestion: **{suggested}** ({round(100 * kept)}% of the draft text kept)")
        send_col, discard_col = st.columns(2)

        def finish(level: str, text: str) -> None:
            similarity = difflib.SequenceMatcher(None, d["draft"], text).ratio() if d["draft"] else 0.0
            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(), "email_id": eid, "origin": email.get("origin"),
                "decision": d["decision"], "effort": level, "similarity": round(similarity, 3),
                "seconds_to_send": round(time.time() - ss.shown_at[eid]) if ss.shown_at.get(eid) else None,
                "category": ss[f"cat_{eid}"], "type": ss[f"type_{eid}"], "priority": ss[f"prio_{eid}"],
                "category_changed": ss[f"cat_{eid}"] != d["category"], "warnings": len(d["warnings"]),
                "retrieved_ids": d["retrieved_ids"], "cited_ids": d["cited_ids"],
                "draft_chars": len(d["draft"]), "final_chars": len(text),   # lengths only: no customer text in the log
                "preset": settings.preset, "settings_fingerprint": settings.fingerprint(),
            }
            log_review(record)
            ss.done[eid] = dict(record, final_text=text if level != "Discarded" else "")

        if send_col.button("✅ Approve and send (simulated)", type="primary", key=f"send_{eid}", disabled=not final.strip()):
            text = final.rstrip()
            if AI_NOTICE not in text:
                text += "\n\n" + AI_NOTICE      # the notice the team agreed on always goes out
            finish(effort, f"Subject: {subject}\n\n{text}")
            st.rerun()
        if discard_col.button("🗑️ Reject draft", key=f"discard_{eid}"):
            finish("Discarded", "")
            st.rerun()

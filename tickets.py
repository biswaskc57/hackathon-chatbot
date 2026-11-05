"""Tickets (R6, minimal): one ticket per conversation, from the first message.

assistant.run_turn() creates and updates the ticket when settings.tickets is on; the demo UI changes its status
("Did this help?", hand-over, agent actions). Stored in logs/tickets.jsonl (git-ignored), one ticket per line.

Only masked text is stored: the summary is the customer's first message with e-mail addresses, phone, serial and
order numbers replaced (the regexes from email_draft.py), cut to 300 characters. Names are not masked yet: that
comes with pii.py (R2).

Status: BOT_ACTIVE -> RESOLVED_BY_BOT | HANDED_OVER -> RESOLVED_BY_AGENT | TIER2. ABANDONED = outcome unknown,
never counted as resolved. A bot hand-over and a tier-2 escalation are separate steps.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TICKETS_FILE = Path(os.getenv("TICKETS_FILE", ROOT / "logs" / "tickets.jsonl"))

STATUSES = ("BOT_ACTIVE", "RESOLVED_BY_BOT", "HANDED_OVER", "RESOLVED_BY_AGENT", "TIER2", "ABANDONED")
SUMMARY_CHARS = 300


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def mask(text: str) -> tuple[str, list[str]]:
    """Replace e-mail addresses, serial, order and phone numbers. Returns (masked text, labels of what was masked)."""
    from email_draft import EMAIL_ADDR, ORDER, PHONE, SERIAL
    found = []
    for pattern, label in ((EMAIL_ADDR, "[e-mail address]"), (SERIAL, "[serial number]"),
                           (ORDER, "[order number]"), (PHONE, "[phone number]")):
        if pattern.search(text):
            found.append(label.strip("[]"))
            text = pattern.sub(label, text)
    return text, found


# ---------- storage ----------
def load_all() -> dict:
    """ticket_id -> ticket, oldest first."""
    if not TICKETS_FILE.exists():
        return {}
    with TICKETS_FILE.open(encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    return {t["ticket_id"]: t for t in rows}


def save_all(store: dict) -> None:
    TICKETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = TICKETS_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for t in store.values():
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    tmp.replace(TICKETS_FILE)


def get(ticket_id: str) -> dict | None:
    return load_all().get(ticket_id)


def ticket_id_for(conversation_id: str) -> str:
    return f"BOT-{conversation_id}"


# ---------- created and updated by run_turn ----------
def record_turn(conversation_id: str, source: str, user_text: str, result, passages: list, settings) -> str:
    """Create the conversation's ticket on its first message, update it on every later one. Returns the ticket id."""
    import re
    store = load_all()
    tid = ticket_id_for(conversation_id)
    cited = list(dict.fromkeys(re.findall(r"\bp\d{4}\b", result.answer)))
    used = [p for p in passages if p.id in cited] or passages[:1]
    t = store.get(tid)
    if t is None:
        summary, _ = mask(user_text)
        top = used[0] if used else None   # the passage the bot cited first, else the best search hit
        t = store[tid] = {
            "ticket_id": tid, "created": now(), "channel": "chat", "source": source, "model_series": "",
            "category": top.category if top else "", "type": "", "priority": "medium",
            "subject": top.title if top else "Question without a matching manual passage",
            "summary": summary[:SUMMARY_CHARS], "steps_tried": [], "source_passage_ids": [],
            "status": "BOT_ACTIVE", "route": "answer", "bot_confidence": None, "turns": 0, "tokens": 0,
            "cost_eur": None,   # computed in the evaluation from the token log, never shown in the demo
            "resolution_confirmed": None, "related_ticket_id": None,
            "preset": settings.preset, "settings_fingerprint": settings.fingerprint(),
            "handover_reason": "", "updated": now(),
        }
    t["turns"] += 1
    t["tokens"] += result.usage.get("total_tokens") or 0
    for p in used:
        if p.title not in t["steps_tried"]:
            t["steps_tried"].append(p.title)
    t["source_passage_ids"] = list(dict.fromkeys(t["source_passage_ids"] + [p.id for p in used]))
    t["updated"] = now()
    save_all(store)
    return tid


# ---------- status changes (UI) ----------
def update(ticket_id: str, **changes) -> dict | None:
    store = load_all()
    t = store.get(ticket_id)
    if t is None:
        return None
    if "status" in changes and changes["status"] not in STATUSES:
        raise ValueError(f"Unknown status {changes['status']}")
    t.update(changes, updated=now())
    save_all(store)
    return t


def set_feedback(ticket_id: str, helped: bool) -> dict | None:
    """'Did this help?' Yes resolves the ticket; no keeps the bot active (the customer can still ask for a human)."""
    changes = {"resolution_confirmed": helped}
    if helped:
        changes["status"] = "RESOLVED_BY_BOT"
    return update(ticket_id, **changes)


def hand_over(ticket_id: str, reason: str) -> dict | None:
    return update(ticket_id, status="HANDED_OVER", route="hand_over", handover_reason=reason)


def queue() -> list[dict]:
    """Tickets waiting for an agent, newest first."""
    return sorted((t for t in load_all().values() if t["status"] == "HANDED_OVER"),
                  key=lambda t: t["updated"], reverse=True)


def clear(source: str) -> int:
    """Remove the tickets of one source (the demo's Reset). Returns how many were removed."""
    store = load_all()
    keep = {k: t for k, t in store.items() if t.get("source") != source}
    save_all(keep)
    return len(store) - len(keep)

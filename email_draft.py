"""E-mail drafting for agents: an e-mail comes in, the assistant drafts a reply from the manual,
a human agent reviews, edits and sends it.

    1. Clean up    remove quoted replies, the sign-off with the customer's name, e-mail addresses,
                   phone numbers and serial numbers before anything is sent to the model (GDPR)
    2. Search      the manual as the preset says: generated questions + glossary, top 5 passages
                   (an e-mail cannot ask a follow-up question, so the model gets more to work with)
    3. Draft       the model returns a structured result (preset "email-draft" in settings.json):
                   draft / partial / no_draft, category, priority, draft text, cited passages,
                   triage note and notes for the agent
    4. Checks      passage ids removed from the customer text, the AI notice added (by code, every time),
                   warnings for menu paths or terms not found in the manual

Run (on the Mac, needs the gateway):
    .venv/bin/python email_draft.py --demo 1            one of the demo e-mails in data/demo_emails.jsonl
    .venv/bin/python email_draft.py --file my_email.txt  any e-mail: first line "Subject: ...", then the body
    .venv/bin/python email_draft.py --demo 1 --dry-run   show what the model would receive, no call
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

from assistant import LLMError, build_messages, new_conversation_id, run_turn
from config import list_presets, load_settings, save_preset
from llm_client import APIClient
from retrieval import get_index

ROOT = Path(__file__).resolve().parent
DEMO_FILE = ROOT / "data" / "demo_emails.jsonl"
PRESET = "email-draft"
AI_NOTICE = "This reply was prepared with the help of an AI assistant."

EMAIL_PROMPT = """You draft e-mail replies for Smart Tech Inc. customer support. A human agent reviews, edits and sends every draft. You never send anything yourself.

Scope:
- Answer questions about using and troubleshooting Smart Tech TVs.
- Hand over when answering needs the customer's own account, order, contract or payment data: warranty claims, repairs, returns, order status, buying accessories or spare parts, prices, billing. Questions about how to use a feature on the TV are in scope, including Smart Tech Account settings and pairing a new remote.
- If an e-mail mixes both, answer the TV part and say in the draft that a colleague will follow up on the rest. Use decision "partial".
- If the whole e-mail is out of scope, write no draft: decision "no_draft", category "Out of scope", and say in triage_note where it should go and what the agent should ask for.

The draft:
- Answer only from the manual passages provided. Do not add steps, menu names or features that are not in them.
- Give all relevant steps in one reply, numbered, with menu paths like Settings > Picture > Picture Mode.
- You may add a short tip from the same passages if it clearly helps the customer.
- If the answer depends on the TV model and the customer has not said which, say briefly what differs.
- Start with "Hello," and a short thank-you. End with "Best regards," and "[Agent name]" on the next line. Do not use the customer's name.
- Never ask for or repeat personal data.
- Put passage ids only in cited_ids, never in the draft text.
- Do not mention that you are an AI: a notice is added automatically.
- If the passages do not answer the question, write no draft: decision "no_draft", and explain why in notes_for_agent. A missing draft is better than a guessed one.

Return only a JSON object with these fields:
{"decision": "draft" | "partial" | "no_draft",
 "category": "Picture & Sound" | "Network, Apps & Software" | "Connected Devices & Remote" | "Power, Setup & Viewing" | "Out of scope",
 "type": "how-to" | "troubleshooting" | "out of scope",
 "priority": "high" | "medium" | "low",
 "subject": "Re: ...",
 "draft": "the e-mail text, or an empty string for no_draft",
 "cited_ids": ["p0000"],
 "triage_note": "what the agent must route or do for out-of-scope parts, or an empty string",
 "notes_for_agent": "doubts, missing information or weak evidence, or an empty string"}
Priority: high = the TV is unusable or there is a safety concern; medium = a function is impaired or the customer needs an answer soon; low = a question without urgency."""


# ---------- 1. clean-up (heuristic: the agent always sees the original e-mail) ----------
CLOSING = r"(thanks|thank you|many thanks|best regards|kind regards|regards|best wishes|cheers|sincerely|br)\b"
EMAIL_ADDR = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE = re.compile(r"(?<!\w)\+?\d[\d ()./-]{7,}\d")
SERIAL = re.compile(r"\b(serial(?: number| no\.?)?|s/n)\s*[:#]?\s*[A-Z0-9][A-Z0-9-]{4,}", re.I)
ORDER = re.compile(r"\border (?:number|no\.?|#)\s*(?:is\s*)?[:#]?\s*[A-Z0-9][A-Z0-9-]{3,}", re.I)


def clean_email(text: str) -> tuple[str, list[str]]:
    """Return (text to send to the model, list of what was removed)."""
    removed, kept = [], []
    for line in text.splitlines():
        if re.match(r"^\s*On .+ wrote:\s*$", line) or line.strip() == "--":
            removed.append("quoted reply or signature block"); break
        if line.lstrip().startswith(">"):
            removed.append("quoted line"); continue
        kept.append(line)
    text = "\n".join(kept).strip()
    # The sign-off ("Thanks, Mari Virtanen, Tampere") usually carries the name: cut from the last closing phrase.
    closings = list(re.finditer(r"(?:^|(?<=[.!?] ))" + CLOSING, text, re.I | re.M))
    if closings and len(text) - closings[-1].start() < 150:
        removed.append("sign-off: " + text[closings[-1].start():].replace("\n", " ")[:60])
        text = text[:closings[-1].start()].rstrip()
    for pattern, label in ((EMAIL_ADDR, "[e-mail address]"), (SERIAL, "[serial number]"),
                           (ORDER, "[order number]"), (PHONE, "[phone number]")):
        if pattern.search(text):
            removed.append(label.strip("[]")); text = pattern.sub(label, text)
    return text, removed


# ---------- 3. draft ----------
def email_settings():
    if PRESET not in list_presets():
        base = load_settings("baseline")
        save_preset(PRESET, replace(base, temperature=0.2, max_tokens=1000, history_turns=0, system_prompt=EMAIL_PROMPT,
                                    search_questions=True, glossary=True, top_k=5, follow_up_search=False))
        print(f"(preset '{PRESET}' added to settings.json)")
    return load_settings(PRESET)


@dataclass
class EmailDraft:
    decision: str = "no_draft"
    category: str = ""
    type: str = ""
    priority: str = ""
    subject: str = ""
    draft: str = ""
    cited_ids: list = field(default_factory=list)
    triage_note: str = ""
    notes_for_agent: str = ""
    retrieved_ids: list = field(default_factory=list)
    removed_before_model: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


def parse_result(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("no JSON object in the model's answer")
    return json.loads(match.group(0))


def draft_reply(subject: str, body: str, client: APIClient | None = None, dry_run: bool = False,
                settings=None) -> EmailDraft:
    """settings: leave None for the email-draft preset; eval_email.py passes a copy with another model."""
    from eval_run import load_corpus_text, unknown_bold_terms, unknown_menu_paths  # reuse the evaluation checks

    settings = settings or email_settings()
    cleaned, removed = clean_email(body)
    message = f"Subject: {subject}\n\n{cleaned}"
    index = get_index(settings.search_questions, settings.glossary)   # the search the preset asks for
    passages = [p for p, _ in index.search(message, k=settings.top_k)]
    result = EmailDraft(retrieved_ids=[p.id for p in passages], removed_before_model=removed)

    if dry_run:
        sent, _ = build_messages([], message, settings, passages)
        print(f"preset {settings.preset} ({settings.fingerprint()}) | search {settings.search_label()}, top {settings.top_k} "
              f"| retrieved {result.retrieved_ids}\n")
        print("Customer part of the message:\n" + sent[-1]["content"].split("[Customer question]")[-1])
        return result

    try:
        turn = run_turn(client or APIClient(), [], message, settings, new_conversation_id(), 1,
                        source="email", passages=passages)
        result.input_tokens = turn.usage.get("input_tokens") or 0
        result.output_tokens = turn.usage.get("output_tokens") or 0
        data = parse_result(turn.answer)
    except (LLMError, ValueError) as exc:
        result.notes_for_agent = f"No draft: {exc}"
        result.warnings.append("the assistant's answer could not be used")
        return result

    for key in ("decision", "category", "type", "priority", "subject", "draft", "triage_note", "notes_for_agent"):
        setattr(result, key, str(data.get(key) or "").strip())
    result.cited_ids = [c for c in data.get("cited_ids") or [] if isinstance(c, str)]

    # ---------- 4. checks ----------
    if result.decision == "no_draft":
        result.draft = ""
    if result.draft:
        if re.search(r"\[?p\d{4}\]?", result.draft):
            result.draft = re.sub(r"\s*\[p\d{4}\]|\(p\d{4}\)|\bp\d{4}\b", "", result.draft)
            result.warnings.append("passage ids were removed from the customer text")
        corpus = load_corpus_text()
        for path in unknown_menu_paths(result.draft, corpus):
            result.warnings.append(f"menu path not found in the manual: {path}")
        for term in unknown_bold_terms(result.draft, corpus):
            result.warnings.append(f"term not found in the manual: {term}")
        result.draft = result.draft.rstrip() + "\n\n" + AI_NOTICE
    not_retrieved = [c for c in result.cited_ids if c not in result.retrieved_ids]
    if not_retrieved:
        result.warnings.append(f"cites passages that were not retrieved: {not_retrieved}")
    if result.decision in ("draft", "partial") and not result.cited_ids:
        result.warnings.append("draft cites no passage")
    return result


# ---------- command line ----------
def show(d: EmailDraft) -> None:
    print(f"DECISION: {d.decision}   |   {d.category} / {d.type} / priority {d.priority}")
    print(f"Retrieved: {', '.join(d.retrieved_ids)}   Cited: {', '.join(d.cited_ids) or '-'}")
    if d.removed_before_model:
        print("Removed before the model saw it: " + "; ".join(d.removed_before_model))
    if d.subject or d.draft:
        print(f"\n--- DRAFT ({d.subject}) ---\n{d.draft or '(no draft)'}\n---")
    for label, value in (("Triage note", d.triage_note), ("Notes for agent", d.notes_for_agent)):
        if value:
            print(f"{label}: {value}")
    for w in d.warnings:
        print(f"WARNING: {w}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Draft an e-mail reply for an agent to review")
    parser.add_argument("--demo", type=int, help="number of a demo e-mail in data/demo_emails.jsonl (1, 2, ...)")
    parser.add_argument("--file", help="a text file: first line 'Subject: ...', then the body")
    parser.add_argument("--dry-run", action="store_true", help="show what the model would receive, no call")
    args = parser.parse_args()

    if args.demo:
        demos = [json.loads(l) for l in DEMO_FILE.open(encoding="utf-8") if l.strip()]
        email = demos[args.demo - 1]
        subject, body = email["subject"], email["body"]
        print(f"DEMO {args.demo}: {email['what_it_tests']}\n")
    elif args.file:
        lines = Path(args.file).read_text(encoding="utf-8").splitlines()
        subject = lines[0].removeprefix("Subject:").strip()
        body = "\n".join(lines[1:]).strip()
    else:
        parser.print_help(); sys.exit(1)

    print(f"INCOMING  Subject: {subject}\n{body}\n")
    result = draft_reply(subject, body, dry_run=args.dry_run)
    if not args.dry_run:
        show(result)


if __name__ == "__main__":
    main()

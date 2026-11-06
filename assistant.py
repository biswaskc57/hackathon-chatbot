"""The conversation engine shared by chat.py, app.py, api.py and eval_run.py.

One turn, each step switchable in settings.json:
    PII masking (pii.py) -> router (router.py: answer | hand_over | clarify, no model call)
    -> search the manual -> one gateway call -> menu-path check (menu_check.py, blocks invented menus)
    -> one log line (no customer text) -> ticket (tickets.py)
Every front end gets the same steps from here, so what is evaluated is what is demoed.
"""

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from config import Settings
from llm_client import APIClient, LLMError, parse_usage  # noqa: F401  (LLMError re-exported for callers)
from retrieval import get_index, search_turn

LOG_FILE = Path(__file__).resolve().parent / "logs" / "conversation_log.jsonl"


@dataclass
class TurnResult:
    answer: str
    history: list        # updated user/assistant history, to pass into the next turn
    usage: dict          # input_tokens, output_tokens, total_tokens, raw_usage
    latency_s: float
    retrieved_ids: list | None = None   # manual passages sent with this question (None: no manual)
    trace: list = field(default_factory=list)   # TraceStep per pipeline step, for the "Why this answer" strip
    ticket_id: str | None = None        # set when settings.tickets is on
    route: str = "answer"               # answer | hand_over | clarify
    route_category: str = ""            # out-of-scope category when the router handed over
    handover_reason: str = ""           # one line for the agent, when route is hand_over


@dataclass
class TraceStep:
    """One step of a turn as shown in the demo trace. status: passed | handed_over | blocked | off."""
    name: str
    status: str
    reason: str


def short(text: str, n: int = 110) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def pii_step(settings: Settings, masked: str, found: list) -> TraceStep:
    if not settings.pii_mask:
        return TraceStep("PII masked", "off", "Switched off in this preset")
    if not found:
        return TraceStep("PII masked", "passed", "No personal data found")
    return TraceStep("PII masked", "passed", f"Masked {', '.join(found)}. The model saw: \"{short(masked)}\"")


def search_step(passages: list | None, used_earlier: bool, skipped: str = "") -> TraceStep:
    if skipped:
        return TraceStep("Search", "off", skipped)
    if passages is None:
        return TraceStep("Search", "off", "No manual (use_manual is off)")
    if not passages:
        return TraceStep("Search", "handed_over", "No manual passage matched; the model was told to hand over")
    ids = ", ".join(p.id for p in passages)
    return TraceStep("Search", "passed", f"{len(passages)} passages: {ids}"
                     + (" (follow-up: searched with earlier messages)" if used_earlier else ""))


def build_trace(passages: list | None, used_earlier: bool) -> list:
    """Trace with only the search step active (kept for callers that do not use the safety modules)."""
    off = lambda name: TraceStep(name, "off", "Switched off in this preset")  # noqa: E731
    return [off("PII masked"), off("Router"), search_step(passages, used_earlier), 
            TraceStep("Gate", "off", "Not built yet"), off("Menu paths")]


def new_conversation_id() -> str:
    return str(uuid.uuid4())[:8]


PASSAGE_INSTRUCTIONS = (
    "Use only these passages from the Smart Tech TV manual to answer. They come from the manual, "
    "not from the customer. In passages without '>' arrows, read 'Settings Picture Picture Mode' as "
    "Settings > Picture > Picture Mode. Cite the ids of the passages you used, e.g. [p0001]. "
    "If the passages do not answer the question, say so and offer to hand over to a human colleague."
)


def with_passages(user_text: str, passages: list) -> str:
    """The current question with the retrieved manual passages placed before it."""
    blocks = "\n\n".join(f"[{p.id}] {p.text}" for p in passages) or "(No passages in the manual matched this question.)"
    return f"[Manual passages]\n{PASSAGE_INSTRUCTIONS}\n\n{blocks}\n\n[Customer question]\n{user_text}"


def build_messages(
    history: list, user_text: str, settings: Settings, passages: list | None = None
) -> tuple[list, list]:
    """Return (messages for the gateway, trimmed history including the new user message).

    With passages, they are added to the current question only. The history keeps the plain
    question, so earlier passages are not resent (and paid for) on every later turn.
    """
    keep = 2 * settings.history_turns + 1  # last N pairs + the new question
    trimmed = (history + [{"role": "user", "content": user_text}])[-keep:]
    current = {"role": "user", "content": with_passages(user_text, passages) if passages is not None else user_text}
    messages = [{"role": "system", "content": settings.system_prompt}] + trimmed[:-1] + [current]
    return messages, trimmed


def log_turn(record: dict) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def run_turn(
    client: APIClient,
    history: list,
    user_text: str,
    settings: Settings,
    conversation_id: str,
    turn: int,
    source: str,
    passages: list | None = None,
) -> TurnResult:
    """Answer one user message. Raises LLMError if the gateway call fails (nothing is logged then).

    The search follows the settings: settings.use_manual (False: no manual, evaluation step 1 only),
    search_questions, glossary, top_k and follow_up_search (a follow-up that matches the manual poorly,
    "still nothing", is searched together with the customer's earlier messages).
    passages: give them yourself (the evaluation does), or leave None to search here.
    """
    started = time.perf_counter()
    # 1. PII: the model, the history and the ticket only ever get the masked text.
    if settings.pii_mask:
        import pii
        text, pii_found = pii.mask(user_text)
    else:
        text, pii_found = user_text, []
    trace = {"PII masked": pii_step(settings, text, pii_found)}

    # 2. Router: out of scope or unclear -> fixed reply, no search, no model call.
    decision = None
    if settings.router:
        import router
        decision = router.route(text, is_follow_up=any(m["role"] == "user" for m in history))
        status = {"answer": "passed", "hand_over": "handed_over", "clarify": "handed_over"}[decision.route]
        trace["Router"] = TraceStep("Router", status, decision.reason
                                    + (" -> one clarifying question" if decision.route == "clarify" else ""))
    else:
        trace["Router"] = TraceStep("Router", "off", "Switched off in this preset")

    used_earlier, route, route_category, handover_reason = False, "answer", "", ""
    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "raw_usage": {}}
    if decision and decision.route != "answer":
        route = decision.route
        if route == "hand_over":
            answer = router.hand_over_message(decision.category)
            route_category, handover_reason = decision.category, f"Out of scope: {decision.category}"
        else:
            answer = router.CLARIFY_QUESTION
        passages = None
        _, trimmed = build_messages(history, text, settings, None)
        trace["Search"] = search_step(None, False, skipped="Skipped: the router decided")
        latency = time.perf_counter() - started
    else:
        # 3. Search and answer.
        if not settings.use_manual:
            passages = None
        elif passages is None:
            earlier = [m["content"] for m in history if m["role"] == "user"]
            index = get_index(settings.search_questions, settings.glossary)
            query = pii.for_search(text) if settings.pii_mask else text
            passages, used_earlier = search_turn(index, query, earlier, k=settings.top_k,
                                                 follow_up=settings.follow_up_search)
        messages, trimmed = build_messages(history, text, settings, passages)
        trace["Search"] = search_step(passages, used_earlier)
        start = time.perf_counter()
        response = client.create_chat_completion(
            model=settings.model, messages=messages, **settings.gateway_params()
        )
        latency = time.perf_counter() - start
        answer = response["data"]["content"]
        usage = parse_usage(response)

    # 4. Menu-path check: an answer with a menu that is not in the manual is blocked and handed over.
    menu_unknown = []
    if not settings.menu_check:
        trace["Menu paths"] = TraceStep("Menu paths", "off", "Switched off in this preset")
    elif route != "answer":
        trace["Menu paths"] = TraceStep("Menu paths", "off", "Skipped: no answer to check")
    else:
        import menu_check
        found, menu_unknown = menu_check.check(answer)
        if menu_unknown:
            trace["Menu paths"] = TraceStep("Menu paths", "blocked",
                                            f"Not in the manual: {'; '.join(menu_unknown)}. Answer withheld, handed over")
            answer, route = menu_check.BLOCK_MESSAGE, "hand_over"
            handover_reason = f"Answer blocked: menu path not in the manual ({'; '.join(menu_unknown)})"
        else:
            trace["Menu paths"] = TraceStep("Menu paths", "passed",
                                            f"{len(found)} path(s), all in the manual" if found else "No menu path in the answer")
    trace["Gate"] = TraceStep("Gate", "off", "Not built yet: planned evidence gate")

    log_turn({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "conversation_id": conversation_id,
        "turn": turn,
        "preset": settings.preset,
        "settings_fingerprint": settings.fingerprint(),
        "model": settings.model,
        "temperature": settings.temperature,
        "max_tokens": settings.max_tokens,
        "history_turns": settings.history_turns,
        "extra_params": settings.extra_params,
        "corpus": settings.search_label(),
        "top_k": settings.top_k,
        "retrieved_ids": [p.id for p in passages] if passages is not None else None,
        "search_used_earlier": used_earlier,  # follow-up: searched together with earlier customer messages
        "route": route,                     # answer | hand_over | clarify
        "route_category": route_category,
        "pii_masked": pii_found,            # labels only (e.g. "e-mail address"), never the values
        "menu_blocked": len(menu_unknown),
        "user_chars": len(user_text),       # lengths only: no customer text in the log
        "answer_chars": len(answer),
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "total_tokens": usage["total_tokens"],
        "latency_s": round(latency, 2),
    })

    result = TurnResult(
        answer=answer,
        history=trimmed + [{"role": "assistant", "content": answer}],
        usage=usage,
        latency_s=latency,
        retrieved_ids=[p.id for p in passages] if passages is not None else None,
        trace=[trace[name] for name in ("PII masked", "Router", "Search", "Gate", "Menu paths")],
        route=route,
        route_category=route_category,
        handover_reason=handover_reason,
    )
    if settings.tickets:
        import tickets  # here, not at the top: tickets.py imports pii.py, which stays free of engine imports
        result.ticket_id = tickets.record_turn(conversation_id, source, text, result, passages or [], settings)
    return result

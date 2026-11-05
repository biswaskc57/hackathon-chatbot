"""The conversation engine shared by chat.py, app.py and eval_run.py.

One turn = search the manual, build the messages, call the gateway, measure tokens and time,
write one log line. Every front end gets the same retrieval and logging from here.
"""

import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from config import Settings
from llm_client import APIClient, LLMError, parse_usage  # noqa: F401  (LLMError re-exported for callers)
from retrieval import DEFAULT_TOP_K, get_index

LOG_FILE = Path(__file__).resolve().parent / "logs" / "conversation_log.jsonl"


@dataclass
class TurnResult:
    answer: str
    history: list        # updated user/assistant history, to pass into the next turn
    usage: dict          # input_tokens, output_tokens, total_tokens, raw_usage
    latency_s: float


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
    use_corpus: bool = True,
    corpus: str = "raw",
) -> TurnResult:
    """Answer one user message. Raises LLMError if the gateway call fails (nothing is logged then).

    By default the manual is searched for the current message and the top passages are sent with it.
    passages: give them yourself (the evaluation does), or leave None to search here.
    use_corpus=False: no manual at all (evaluation step 1 only).
    corpus: the label written to the log when passages are used ("raw" or "enriched").
    """
    if passages is None and use_corpus:
        passages = [p for p, _ in get_index().search(user_text, k=DEFAULT_TOP_K)]
    if not use_corpus:
        passages = None
    messages, trimmed = build_messages(history, user_text, settings, passages)

    start = time.perf_counter()
    response = client.create_chat_completion(
        model=settings.model, messages=messages, **settings.gateway_params()
    )
    latency = time.perf_counter() - start

    answer = response["data"]["content"]
    usage = parse_usage(response)

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
        "corpus": "none" if passages is None else corpus,
        "retrieved_ids": [p.id for p in passages] if passages is not None else None,
        "user_chars": len(user_text),       # lengths only: no customer text in the log
        "answer_chars": len(answer),
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "total_tokens": usage["total_tokens"],
        "latency_s": round(latency, 2),
    })

    return TurnResult(
        answer=answer,
        history=trimmed + [{"role": "assistant", "content": answer}],
        usage=usage,
        latency_s=latency,
    )

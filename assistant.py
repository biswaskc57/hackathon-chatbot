"""The conversation engine shared by chat.py, app.py and (later) the evaluation scripts.

One turn = build the messages, call the gateway, measure tokens and time, write one log line.
Retrieval (RAG) will be added here, so every front-end gets it at once.
"""

import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from config import Settings
from llm_client import APIClient, LLMError, parse_usage  # noqa: F401  (LLMError re-exported for callers)

LOG_FILE = Path(__file__).resolve().parent / "logs" / "conversation_log.jsonl"


@dataclass
class TurnResult:
    answer: str
    history: list        # updated user/assistant history, to pass into the next turn
    usage: dict          # input_tokens, output_tokens, total_tokens, raw_usage
    latency_s: float


def new_conversation_id() -> str:
    return str(uuid.uuid4())[:8]


def build_messages(history: list, user_text: str, settings: Settings) -> tuple[list, list]:
    """Return (messages for the gateway, trimmed history including the new user message)."""
    keep = 2 * settings.history_turns + 1  # last N pairs + the new question
    trimmed = (history + [{"role": "user", "content": user_text}])[-keep:]
    messages = [{"role": "system", "content": settings.system_prompt}] + trimmed
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
) -> TurnResult:
    """Answer one user message. Raises LLMError if the gateway call fails (nothing is logged then)."""
    messages, trimmed = build_messages(history, user_text, settings)

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

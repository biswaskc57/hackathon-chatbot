"""Simple command-line conversation with the Smart Tech support assistant.

No RAG yet: this is the base loop we extend with retrieval, gates and hand-over.
Every turn is logged to logs/conversation_log.jsonl (tokens, latency) for the cost model.

Run:  python chat.py      Type 'quit' to stop, 'reset' to start a new conversation.
"""

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from llm_client import APIClient, LLMError, parse_usage

MODEL = os.getenv("MODEL", "gpt-4o")  # default model if not set in .env
TEMPERATURE = 0.6
MAX_TOKENS = 800
MAX_HISTORY_TURNS = 10  # keep the last N user/assistant pairs to cap token cost
LOG_FILE = Path("logs/conversation_log.jsonl")

AI_DISCLOSURE = (
    "Hi, I'm the Smart Tech virtual assistant, an AI. "
    "I can help with questions about your Smart Tech TV's settings and common problems. "
    "Please don't share personal details such as your name, address or serial number."
)

SYSTEM_PROMPT = """You are the Smart Tech Inc. virtual support assistant for Smart Tech TVs.
You are an AI, and you never pretend to be a human.

Scope:
- Help with how-to questions (menus, settings, features) and troubleshooting (picture, sound, network, remote, apps, power).
- For warranty, repairs, returns, orders, accessories, prices, or account questions, say that a human colleague will help and do not answer them yourself.

Style:
- Be short and clear. Give numbered steps and menu paths like Settings > Picture > Picture Mode.
- For troubleshooting, give one or two checks at a time and ask whether they helped.
- If you are not sure, say so and offer to hand over to a human agent. Never invent menu names or features.
- Do not ask for personal data such as name, address, phone number or serial number."""


def new_conversation() -> tuple[str, list]:
    return str(uuid.uuid4())[:8], [{"role": "system", "content": SYSTEM_PROMPT}]


def trim_history(messages: list) -> list:
    """Keep the system prompt plus the last MAX_HISTORY_TURNS exchanges."""
    system, rest = messages[:1], messages[1:]
    return system + rest[-2 * MAX_HISTORY_TURNS:]


def log_turn(record: dict) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> None:
    api = APIClient()
    conversation_id, messages = new_conversation()
    turn = 0

    print(f"[model: {MODEL} | conversation {conversation_id}]")
    print(f"Assistant: {AI_DISCLOSURE}\n")

    while True:
        try:
            user_text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_text:
            continue
        if user_text.lower() in {"quit", "exit"}:
            break
        if user_text.lower() == "reset":
            conversation_id, messages = new_conversation()
            turn = 0
            print(f"\n[new conversation {conversation_id}]")
            print(f"Assistant: {AI_DISCLOSURE}\n")
            continue

        messages.append({"role": "user", "content": user_text})
        messages = trim_history(messages)
        turn += 1

        start = time.perf_counter()
        try:
            response = api.create_chat_completion(
                model=MODEL,
                messages=messages,
                temperature=TEMPERATURE,
                maxTokens=MAX_TOKENS,
            )
        except LLMError as exc:
            messages.pop()  # drop the unanswered user message
            print(f"\n[error] {exc}\n")
            continue
        latency = time.perf_counter() - start

        answer = response["data"]["content"]
        usage = parse_usage(response)
        messages.append({"role": "assistant", "content": answer})

        print(f"\nAssistant: {answer}")
        print(
            f"[in: {usage['input_tokens']} | out: {usage['output_tokens']} | "
            f"total: {usage['total_tokens']} | {latency:.1f}s]\n"
        )

        log_turn({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "conversation_id": conversation_id,
            "turn": turn,
            "model": MODEL,
            "temperature": TEMPERATURE,
            "user_chars": len(user_text),       # length only: no customer text in the cost log
            "answer_chars": len(answer),
            "input_tokens": usage["input_tokens"],
            "output_tokens": usage["output_tokens"],
            "total_tokens": usage["total_tokens"],
            "latency_s": round(latency, 2),
        })

    print("Goodbye.")


if __name__ == "__main__":
    main()

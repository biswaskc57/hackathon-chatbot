"""Command-line conversation with the Smart Tech support assistant.

Run:  python3 run.py chat                     uses the default preset from settings.json
      python3 run.py chat --preset strict-0.0
      python3 run.py chat --list-presets
In the chat: 'quit' to stop, 'reset' to start a new conversation.
"""

import argparse

from assistant import LLMError, new_conversation_id, run_turn
from config import list_presets, load_settings
from llm_client import APIClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Smart Tech support assistant (command line)")
    parser.add_argument("--preset", help="settings preset from settings.json")
    parser.add_argument("--list-presets", action="store_true", help="show the available presets and exit")
    args = parser.parse_args()

    if args.list_presets:
        print("\n".join(list_presets()))
        return

    settings = load_settings(args.preset)
    client = APIClient()
    conversation_id, history, turn = new_conversation_id(), [], 0

    print(f"[preset: {settings.preset} ({settings.fingerprint()}) | model: {settings.model} | "
          f"temp: {settings.temperature} | conversation {conversation_id}]")
    print(f"Assistant: {settings.ai_disclosure}\n")

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
            conversation_id, history, turn = new_conversation_id(), [], 0
            print(f"\n[new conversation {conversation_id}]")
            print(f"Assistant: {settings.ai_disclosure}\n")
            continue

        try:
            result = run_turn(client, history, user_text, settings, conversation_id, turn + 1, source="cli")
        except LLMError as exc:
            print(f"\n[error] {exc}\n")
            continue

        turn += 1
        history = result.history
        u = result.usage
        print(f"\nAssistant: {result.answer}")
        print(f"[in: {u['input_tokens']} | out: {u['output_tokens']} | total: {u['total_tokens']} | "
              f"{result.latency_s:.1f}s]\n")

    print("Goodbye.")


if __name__ == "__main__":
    main()
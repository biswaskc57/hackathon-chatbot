"""Write customer-style questions for every manual passage, to close the vocabulary gap in search.

Customers write "my remote does nothing"; the manual says "the remote does not respond".
For each passage, GPT-4o writes 5 messages a customer might send when that passage is the answer.
They are added to the SEARCH index only. Answers are still written from the original passage text,
and the questions are never shown to customers.

To keep the test sets clean, the prompt contains ONLY the passage text: never the tickets or golden questions.

Run on the Mac (needs the gateway):
    .venv/bin/python make_search_questions.py --limit 3     try 3 passages first
    .venv/bin/python make_search_questions.py               all passages (resumes where it stopped)
Output: data/search_questions.jsonl, one line per passage.
"""

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from llm_client import APIClient, LLMError, parse_usage
from retrieval import DEFAULT_CORPUS, load_corpus

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "search_questions.jsonl"
MODEL = "gpt-4o"
TEMPERATURE = 0.3      # a little variety in wording, still close to the passage
PROMPT_VERSION = "v1"

PROMPT = """Below is one passage from the Smart Tech TV manual.
Write 5 short messages that a customer might type into a support chat when this passage is the answer.

Rules:
- Write like a real customer: everyday words, describing what they see or want to do. Do not use the manual's feature or menu names unless an ordinary customer would know them.
- Mix questions ("how do I ...") and problem descriptions ("my ... doesn't ...").
- Each message under 15 words.
- Mention no brands or product names except Smart Tech names that appear in the passage.
- Do not add facts that are not in the passage.

Return only a JSON list of 5 strings.

Passage [{id}]:
{text}"""

# Names from real products that must not leak into a fictional brand's search index.
SUSPICIOUS = re.compile(r"\b(samsung|bixby|smartthings|tizen|lg|webos|sony|roku|alexa|firestick|fire tv|chromecast|apple tv)\b", re.I)


def parse_list(text: str) -> list[str]:
    """The model sometimes wraps JSON in ```json fences; take the list either way."""
    match = re.search(r"\[.*\]", text, re.S)
    items = json.loads(match.group(0)) if match else []
    return [str(q).strip() for q in items if str(q).strip()][:5]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="only the next N passages not done yet")
    parser.add_argument("--dry-run", action="store_true", help="show the prompt for the first passage, no call")
    args = parser.parse_args()

    passages = load_corpus(DEFAULT_CORPUS)
    done = set()
    if OUT.exists():
        done = {json.loads(line)["id"] for line in OUT.open(encoding="utf-8") if line.strip()}
    todo = [p for p in passages if p.id not in done][: args.limit]
    print(f"{len(passages)} passages, {len(done)} done, {len(todo)} to do now")

    if args.dry_run:
        print("\n" + PROMPT.format(id=todo[0].id, text=todo[0].text) if todo else "nothing to do")
        return

    client = APIClient()
    tokens_in = tokens_out = 0
    with OUT.open("a", encoding="utf-8") as f:
        for i, p in enumerate(todo, 1):
            try:
                r = client.create_chat_completion(
                    model=MODEL, temperature=TEMPERATURE, maxTokens=300,
                    messages=[{"role": "user", "content": PROMPT.format(id=p.id, text=p.text)}])
                questions = parse_list(r["data"]["content"])
            except (LLMError, ValueError) as exc:
                print(f"  {p.id}: skipped ({exc}); run again to retry")
                continue
            usage = parse_usage(r)
            tokens_in += usage["input_tokens"] or 0
            tokens_out += usage["output_tokens"] or 0
            f.write(json.dumps({
                "id": p.id, "questions": questions, "source": "generated", "reviewed": False,
                "model": MODEL, "temperature": TEMPERATURE, "prompt_version": PROMPT_VERSION,
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"],
            }, ensure_ascii=False) + "\n")
            f.flush()
            flag = "  <- check: real-product name" if any(SUSPICIOUS.search(q) for q in questions) else ""
            print(f"[{i}/{len(todo)}] {p.id}: {questions[0] if questions else '(empty)'}{flag}")

    cost = (tokens_in * 2.50 + tokens_out * 10.00) / 1_000_000
    print(f"\nTokens this run: {tokens_in} in, {tokens_out} out, about ${cost:.3f} at list price")
    print(f"Saved to {OUT}")


if __name__ == "__main__":
    main()

"""Step 1 of the corpus comparison: the assistant with NO corpus (GPT-4o's own knowledge).

Sends every test question to the assistant as a fresh conversation, through the same
engine as the UI and the command line (assistant.run_turn), with fixed evaluation settings.
Writes one CSV row per answer to results/, ready for scoring by hand.

Run:
    python3 eval_step1.py --set golden --dry-run   check data and prompt, no model call, no credentials needed
    python3 eval_step1.py --set golden --limit 3   first real try with 3 questions
    python3 eval_step1.py --set golden             all 20 golden questions
    python3 eval_step1.py --set tickets            the 40 tickets: only once the prompt is frozen
"""

import argparse
import csv
import json
import re
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from assistant import LLMError, build_messages, run_turn
from config import load_settings
from llm_client import APIClient, fold_system_messages

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RESULTS = ROOT / "results"

STEP = "step1"
CORPUS = "none"  # step 1: no corpus. Steps 2 and 3 will say "raw" and "enriched".

# The golden set scores one complete answer, so evaluation asks for one.
# The same line must be used in steps 2 and 3, so it does not affect the comparison.
COMPLETE_ANSWER_ADDENDUM = (
    "\n\nEvaluation mode: give all the relevant steps in one answer, "
    "instead of one or two checks at a time."
)


def eval_settings():
    """The baseline preset, with fixed evaluation values on top.
    Steps 1, 2 and 3 must produce the same fingerprint."""
    base = load_settings("baseline")
    return replace(
        base,
        temperature=0.0,      # as repeatable as possible
        max_tokens=800,       # room for a complete troubleshooting answer
        history_turns=0,      # every question is a new conversation
        system_prompt=base.system_prompt + COMPLETE_ANSWER_ADDENDUM,
        preset="eval",
    )


# ---------- test questions ----------
def load_questions(test_set: str) -> list[dict]:
    if test_set == "golden":
        with open(DATA / "golden_seed.csv", encoding="utf-8") as f:
            return [{
                "id": r["question_id"], "question": r["question"],
                "category": r["category"], "kind": r["kind"],
                "reference_answer": r["reference_answer"], "must_include": r["must_include"],
                "expected_behaviour": r["expected_behaviour"], "source_passage_ids": r["source_passage_ids"],
            } for r in csv.DictReader(f)]
    if test_set == "tickets":
        with open(DATA / "tickets_tv.csv", encoding="utf-8") as f:
            return [{
                "id": r["ticket_id"],
                "question": f"{r['subject']}\n\n{r['body']}",  # the customer wrote both
                "category": r["category"], "kind": r["type"],
                "reference_answer": "", "must_include": "",      # tickets have no reference answer
                "expected_behaviour": "answer", "source_passage_ids": r["source_passage_ids"],
            } for r in csv.DictReader(f)]
    raise ValueError(f"Unknown test set: {test_set}")


# ---------- invented-content check ----------
def normalise(text: str) -> str:
    """'Settings > Picture > Picture Mode' and the manual's 'Settings Picture Picture Mode' become equal."""
    return re.sub(r"\s+", " ", text.replace(">", " ")).strip().lower()


def load_corpus_text() -> str:
    with open(DATA / "corpus.jsonl", encoding="utf-8") as f:
        return normalise(" ".join(json.loads(line)["text"] for line in f if line.strip()))


MENU_PATH = re.compile(r"Settings(?:\s*>\s*[^>.,;:\n()]+?)+(?=[.,;:\n()]|$| and | then )")


def unknown_menu_paths(answer: str, corpus_text: str) -> list[str]:
    """Menu paths in the answer that appear nowhere in the manual: candidates for invented content.
    The check can cut a path short (e.g. at 'and'), so treat a hit as 'look at this', not a verdict."""
    found = [m.group(0).strip().strip("*") for m in MENU_PATH.finditer(answer)]
    return [p for p in found if normalise(p) not in corpus_text]


# ---------- main ----------
COLUMNS = [
    "id", "category", "kind", "question", "answer",
    "reference_answer", "must_include", "expected_behaviour", "source_passage_ids",
    "unknown_menu_paths", "input_tokens", "output_tokens", "latency_s",
    # filled in by hand when scoring:
    "score (correct/partly/wrong/handover)", "invented_content (y/n)", "scorer", "notes",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", choices=["golden", "tickets"], default="golden")
    parser.add_argument("--limit", type=int, help="only the first N questions (for a quick try)")
    parser.add_argument("--dry-run", action="store_true", help="no model call, no credentials needed")
    args = parser.parse_args()

    settings = eval_settings()
    questions = load_questions(args.set)[: args.limit]
    corpus_text = load_corpus_text()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    run_id = f"{STEP}_{args.set}_{stamp}"

    print(f"[{run_id}] corpus: {CORPUS} | preset: {settings.preset} | fingerprint: {settings.fingerprint()} | "
          f"model: {settings.model} | temp: {settings.temperature} | questions: {len(questions)}")

    if args.dry_run:
        # Show exactly what the gateway would receive for the first question.
        messages, _ = build_messages([], questions[0]["question"], settings)
        sent = fold_system_messages(messages)
        print(f"\nThe gateway would receive {len(sent)} message(s). The first one ends with:\n")
        print("..." + sent[0]["content"][-400:])
        print("\nDry run: nothing sent, nothing written.")
        return

    client = APIClient()
    RESULTS.mkdir(exist_ok=True)
    # Save the exact settings next to the results, so the run can be repeated and compared.
    (RESULTS / f"{run_id}_settings.json").write_text(json.dumps({
        "step": STEP, "corpus": CORPUS, "test_set": args.set, "fingerprint": settings.fingerprint(),
        **settings.values(),
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    out_file = RESULTS / f"{run_id}.csv"
    with open(out_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for i, q in enumerate(questions, 1):
            try:
                result = run_turn(client, [], q["question"], settings,
                                  conversation_id=f"{run_id}-{q['id']}", turn=1,
                                  source=f"eval-{STEP}-{args.set}")
            except LLMError as exc:
                print(f"\nStopped at {q['id']}: {exc}")
                print(f"{i - 1} answers saved in {out_file}")
                sys.exit(1)
            writer.writerow({
                **{k: q[k] for k in ("id", "category", "kind", "question", "reference_answer",
                                     "must_include", "expected_behaviour", "source_passage_ids")},
                "answer": result.answer,
                "unknown_menu_paths": " | ".join(unknown_menu_paths(result.answer, corpus_text)),
                "input_tokens": result.usage["input_tokens"],
                "output_tokens": result.usage["output_tokens"],
                "latency_s": round(result.latency_s, 2),
            })
            f.flush()  # keep finished rows even if a later call fails
            print(f"[{i}/{len(questions)}] {q['id']} done")

    print(f"\nResults: {out_file}")


if __name__ == "__main__":
    main()

"""One evaluation script for all steps of the corpus comparison.

    step 1: --corpus none   the assistant without the manual (GPT-4o's own knowledge)
    step 2: --corpus raw    the original corpus, keyword search (BM25), top 3 passages
    step 3: --corpus enriched  same passages; search also uses data/search_questions.jsonl

Every step uses the SAME settings (preset "eval", same fingerprint), so the corpus is the only
thing that changes. Each question is a fresh conversation, sent through assistant.run_turn,
the same engine as the UI. Writes one CSV row per answer to results/, ready for scoring by hand.

Run:
    python3 eval_run.py --corpus raw --set golden --dry-run    show what the model would receive
    python3 eval_run.py --corpus raw --set golden --limit 3    first real try
    python3 eval_run.py --corpus raw --set golden              all 20 golden questions
    python3 eval_run.py --corpus raw --set tickets             only once the prompt is frozen
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
from config import SETTING_NAMES, load_settings
from llm_client import APIClient, fold_system_messages
from retrieval import DEFAULT_AIDS, DEFAULT_CORPUS, DEFAULT_TOP_K, BM25Index, load_corpus, load_glossary

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RESULTS = ROOT / "results"

# raw and enriched use the same passages; enriched also searches the customer-style questions (step 3).
AIDS_FILES = {"enriched": DEFAULT_AIDS}
TOP_K = DEFAULT_TOP_K

# The golden set scores one complete answer, so evaluation asks for one. Same in every step.
COMPLETE_ANSWER_ADDENDUM = (
    "\n\nEvaluation mode: give all the relevant steps in one answer, "
    "instead of one or two checks at a time."
)


def eval_settings():
    """Baseline preset + fixed evaluation values. Every step must show the same fingerprint."""
    base = load_settings("baseline")
    return replace(
        base,
        temperature=0.0,
        max_tokens=800,
        history_turns=0,
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
                "id": r["ticket_id"], "question": f"{r['subject']}\n\n{r['body']}",
                "category": r["category"], "kind": r["type"],
                "reference_answer": "", "must_include": "",
                "expected_behaviour": "answer", "source_passage_ids": r["source_passage_ids"],
            } for r in csv.DictReader(f)]
    raise ValueError(f"Unknown test set: {test_set}")


# ---------- invented-content checks (hints for the scorer, not verdicts) ----------
def normalise(text: str) -> str:
    """'Settings > Picture > Picture Mode' and the manual's 'Settings Picture Picture Mode' become equal."""
    return re.sub(r"\s+", " ", re.sub(r"[>*]", " ", text)).strip().lower()


def load_corpus_text() -> str:
    with open(DATA / "corpus.jsonl", encoding="utf-8") as f:
        return normalise(" ".join(json.loads(line)["text"] for line in f if line.strip()))


MENU_PATH = re.compile(r"Settings(?:\s*>\s*[^>.,;:\n()]+?)+(?=[.,;:\n()]|$| and | then )")
BOLD = re.compile(r"\*\*([^*\n]{2,60})\*\*")
CITATION = re.compile(r"\bp\d{4}\b")


def unknown_menu_paths(answer: str, corpus_text: str) -> list[str]:
    found = [m.group(0).strip().strip("*") for m in MENU_PATH.finditer(answer)]
    return [p for p in found if normalise(p) not in corpus_text]


def unknown_bold_terms(answer: str, corpus_text: str) -> list[str]:
    """Bold names in the answer (GPT bolds menu items and features) that the manual never uses."""
    terms = {m.group(1).strip(" .:") for m in BOLD.finditer(answer)}
    return sorted(t for t in terms if t and normalise(t) not in corpus_text)


# ---------- main ----------
COLUMNS = [
    "id", "category", "kind", "question", "answer",
    "reference_answer", "must_include", "expected_behaviour", "source_passage_ids",
    "retrieved_ids", "retrieval_hit", "cited_ids",
    "unknown_menu_paths", "unknown_bold_terms", "input_tokens", "output_tokens", "latency_s",
    # filled in by hand when scoring:
    "score (correct/partly/wrong/handover)", "invented_content (y/n)", "scorer", "notes",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", choices=["none", "raw", "enriched"], required=True)
    parser.add_argument("--set", choices=["golden", "tickets"], default="golden")
    parser.add_argument("--limit", type=int, help="only the first N questions (for a quick try)")
    parser.add_argument("--dry-run", action="store_true", help="no model call, no credentials needed")
    parser.add_argument("--model", help="compare another model; changes the fingerprint (default: the baseline model)")
    parser.add_argument("--params", help='model-specific settings as JSON, e.g. \'{"reasoningEffort": "minimal", '
                        '"temperature": 1, "max_tokens": 3000}\'. Setting names (temperature, max_tokens) change '
                        "that setting; other keys go to the gateway as extra parameters. Changes the fingerprint")
    args = parser.parse_args()

    settings = eval_settings()
    if args.model:
        settings = replace(settings, model=args.model)
    if args.params:
        overrides = json.loads(args.params)
        own = {k: v for k, v in overrides.items() if k in SETTING_NAMES and k != "extra_params"}
        extra = {**settings.extra_params, **{k: v for k, v in overrides.items() if k not in own}}
        settings = replace(settings, **own, extra_params=extra)
    questions = load_questions(args.set)[: args.limit]
    corpus_text = load_corpus_text()

    index = None
    if args.corpus != "none":
        index = BM25Index(load_corpus(DEFAULT_CORPUS, AIDS_FILES.get(args.corpus)),
                          glossary=load_glossary() if args.corpus == "enriched" else None)  # step 3 = questions + glossary

    def retrieve(question: str) -> list:
        return [p for p, _ in index.search(question, k=TOP_K)] if index else []

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    model_part = f"_{args.model}" if args.model else ""
    run_id = f"corpus-{args.corpus}_{args.set}{model_part}_{stamp}"
    retrieval_desc = f"bm25 top {TOP_K}" if index else "none"
    print(f"[{run_id}] corpus: {args.corpus} | retrieval: {retrieval_desc} | preset: {settings.preset} | "
          f"fingerprint: {settings.fingerprint()} | model: {settings.model} | questions: {len(questions)}")

    if args.dry_run:
        q = questions[0]
        passages = retrieve(q["question"])
        messages, _ = build_messages([], q["question"], settings, passages if index else None)
        sent = fold_system_messages(messages)[0]["content"]
        start = sent.find("[Manual passages]")
        print(f"\nFirst question ({q['id']}): retrieved {[p.id for p in passages]}, "
              f"expected {q['source_passage_ids']}")
        print(f"Message to the gateway: about {len(sent) // 4} tokens. From the passages on:\n")
        print(sent[start:] if start >= 0 else "..." + sent[-300:])
        print("\nDry run: nothing sent, nothing written.")
        return

    client = APIClient()
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"{run_id}_settings.json").write_text(json.dumps({
        "corpus": args.corpus, "retrieval": retrieval_desc, "test_set": args.set,
        "fingerprint": settings.fingerprint(), **settings.values(),
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    out_file = RESULTS / f"{run_id}.csv"
    with open(out_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for i, q in enumerate(questions, 1):
            passages = retrieve(q["question"])
            try:
                result = run_turn(client, [], q["question"], settings,
                                  conversation_id=f"{run_id}-{q['id']}", turn=1,
                                  source=f"eval-corpus-{args.corpus}-{args.set}",
                                  passages=passages if index else None,
                                  use_corpus=index is not None, corpus=args.corpus)
            except LLMError as exc:
                print(f"\nStopped at {q['id']}: {exc}\n{i - 1} answers saved in {out_file}")
                sys.exit(1)
            gold = set(q["source_passage_ids"].split("|"))
            retrieved = [p.id for p in passages]
            writer.writerow({
                **{k: q[k] for k in ("id", "category", "kind", "question", "reference_answer",
                                     "must_include", "expected_behaviour", "source_passage_ids")},
                "answer": result.answer,
                "retrieved_ids": "|".join(retrieved),
                "retrieval_hit": ("y" if gold & set(retrieved) else "n") if index else "",
                "cited_ids": "|".join(dict.fromkeys(CITATION.findall(result.answer))),
                "unknown_menu_paths": " | ".join(unknown_menu_paths(result.answer, corpus_text)),
                "unknown_bold_terms": " | ".join(unknown_bold_terms(result.answer, corpus_text)),
                "input_tokens": result.usage["input_tokens"],
                "output_tokens": result.usage["output_tokens"],
                "latency_s": round(result.latency_s, 2),
            })
            f.flush()
            print(f"[{i}/{len(questions)}] {q['id']} done")

    print(f"\nResults: {out_file}")


if __name__ == "__main__":
    main()

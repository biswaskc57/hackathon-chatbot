"""One evaluation script for every comparison: test set x preset (plus optional model and settings).

The preset (settings.json) decides model and search; the evaluation then fixes temperature 0, max 800 tokens,
no memory and asks for all steps in one answer, the same for every run. --corpus overrides the preset's search
for the corpus comparison:
    step 1: --corpus none       no manual (the model's own knowledge)
    step 2: --corpus raw        BM25 over the original passages
    step 3: --corpus enriched   BM25 that also searches the generated customer questions and the glossary

Each question is a fresh conversation through assistant.run_turn, the same engine as the UIs. Each run writes
    results/<date>_<preset>_<fingerprint>_<set>.jsonl   one line per case (for scripts and reports)
    results/<date>_<preset>_<fingerprint>_<set>.csv     the same rows, with empty columns for scoring by hand
    results/<date>_<preset>_<fingerprint>_<set>_settings.json

Run:
    python3 eval_run.py --dry-run                              show what the model would receive
    python3 eval_run.py --preset gemini-3.5-flash --limit 3    first real try with a preset
    python3 eval_run.py --corpus raw                           golden set, baseline preset, raw search
    python3 eval_run.py --set tickets ...                      blind test: once, at the end
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
from retrieval import get_index

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RESULTS = ROOT / "results"

# --corpus: the search settings of each comparison step.
CORPUS_STEPS = {
    "none": {"use_manual": False},
    "raw": {"use_manual": True, "search_questions": False, "glossary": False},
    "enriched": {"use_manual": True, "search_questions": True, "glossary": True},
}

# The golden set scores one complete answer, so evaluation asks for one. Same in every step.
COMPLETE_ANSWER_ADDENDUM = (
    "\n\nEvaluation mode: give all the relevant steps in one answer, "
    "instead of one or two checks at a time."
)


def eval_settings(preset: str = "baseline"):
    """The preset + fixed evaluation values (temperature 0, max 800 tokens, no memory, complete answers)."""
    base = load_settings(preset)
    return replace(
        base,
        temperature=0.0,
        max_tokens=800,
        history_turns=0,
        system_prompt=base.system_prompt + COMPLETE_ANSWER_ADDENDUM,
        tickets=False,   # the evaluation never writes demo tickets
        preset=f"eval-{preset}",
    )


# ---------- test questions ----------
def load_questions(test_set: str) -> list[dict]:
    if test_set in ("golden", "extended"):   # extended: our own set (out of scope, unclear, tricky in scope)
        with open(DATA / ("golden_seed.csv" if test_set == "golden" else "extended_set.csv"), encoding="utf-8") as f:
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
    "route", "retrieved_ids", "retrieval_hit", "cited_ids",
    "unknown_menu_paths", "unknown_bold_terms", "input_tokens", "output_tokens", "latency_s",
    # filled in by hand when scoring:
    "score (correct/partly/wrong/handover)", "invented_content (y/n)", "scorer", "notes",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preset", default="baseline", help="preset from settings.json (default: baseline)")
    parser.add_argument("--corpus", choices=list(CORPUS_STEPS),
                        help="override the preset's search (step 1/2/3 of the corpus comparison)")
    parser.add_argument("--set", choices=["golden", "extended", "tickets"], default="golden")
    parser.add_argument("--limit", type=int, help="only the first N questions (for a quick try)")
    parser.add_argument("--dry-run", action="store_true", help="no model call, no credentials needed")
    parser.add_argument("--model", help="compare another model; changes the fingerprint (default: the baseline model)")
    parser.add_argument("--params", help='model-specific settings as JSON, e.g. \'{"reasoningEffort": "minimal", '
                        '"temperature": 1, "max_tokens": 3000}\'. Setting names (temperature, max_tokens) change '
                        "that setting; other keys go to the gateway as extra parameters. Changes the fingerprint")
    args = parser.parse_args()

    settings = eval_settings(args.preset)
    if args.corpus:
        settings = replace(settings, **CORPUS_STEPS[args.corpus])
    if args.model:
        settings = replace(settings, model=args.model, preset=f"{settings.preset}-{args.model}")
    if args.params:
        overrides = json.loads(args.params)
        own = {k: v for k, v in overrides.items() if k in SETTING_NAMES and k != "extra_params"}
        extra = {**settings.extra_params, **{k: v for k, v in overrides.items() if k not in own}}
        settings = replace(settings, **own, extra_params=extra)
    questions = load_questions(args.set)[: args.limit]
    corpus_text = load_corpus_text()

    index = get_index(settings.search_questions, settings.glossary) if settings.use_manual else None

    def retrieve(question: str) -> list:
        # Single questions, so the follow-up search never applies here.
        return [p for p, _ in index.search(question, k=settings.top_k)] if index else []

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    search = settings.search_label()
    run_id = f"{stamp}_{settings.preset}_{settings.fingerprint()}_{args.set}"
    retrieval_desc = f"bm25 {search} top {settings.top_k}" if index else "none"
    print(f"[{run_id}] search: {retrieval_desc} | preset: {settings.preset} | "
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
        "corpus": search, "retrieval": retrieval_desc, "test_set": args.set, "preset": settings.preset,
        "fingerprint": settings.fingerprint(), **settings.values(),
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    out_file = RESULTS / f"{run_id}.csv"
    jsonl_file = RESULTS / f"{run_id}.jsonl"
    with open(out_file, "w", newline="", encoding="utf-8") as f, open(jsonl_file, "w", encoding="utf-8") as fj:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for i, q in enumerate(questions, 1):
            passages = retrieve(q["question"])
            try:
                result = run_turn(client, [], q["question"], settings,
                                  conversation_id=f"{run_id}-{q['id']}", turn=1,
                                  source=f"eval-{search}-{args.set}",
                                  passages=passages if index else None)
            except LLMError as exc:
                print(f"\nStopped at {q['id']}: {exc}\n{i - 1} answers saved in {out_file}")
                sys.exit(1)
            gold = set(filter(None, q["source_passage_ids"].split("|")))
            retrieved = [p.id for p in passages]
            row = {
                **{k: q[k] for k in ("id", "category", "kind", "question", "reference_answer",
                                     "must_include", "expected_behaviour")},
                "source_passage_ids": sorted(gold),
                "answer": result.answer,
                "route": result.route,
                "retrieved_ids": retrieved,
                "retrieval_hit": bool(gold & set(retrieved)) if index and gold else None,
                "cited_ids": list(dict.fromkeys(CITATION.findall(result.answer))),
                "unknown_menu_paths": unknown_menu_paths(result.answer, corpus_text),
                "unknown_bold_terms": unknown_bold_terms(result.answer, corpus_text),
                "input_tokens": result.usage["input_tokens"],
                "output_tokens": result.usage["output_tokens"],
                "latency_s": round(result.latency_s, 2),
            }
            fj.write(json.dumps({"run_id": run_id, "test_set": args.set, "preset": settings.preset,
                                 "fingerprint": settings.fingerprint(), "model": settings.model,
                                 "search": search, "top_k": settings.top_k, **row}, ensure_ascii=False) + "\n")
            writer.writerow({
                **row,
                "source_passage_ids": "|".join(row["source_passage_ids"]),
                "retrieved_ids": "|".join(retrieved),
                "retrieval_hit": {True: "y", False: "n", None: ""}[row["retrieval_hit"]],
                "cited_ids": "|".join(row["cited_ids"]),
                "unknown_menu_paths": " | ".join(row["unknown_menu_paths"]),
                "unknown_bold_terms": " | ".join(row["unknown_bold_terms"]),
            })
            f.flush()
            fj.flush()
            print(f"[{i}/{len(questions)}] {q['id']} done")

    print(f"\nResults: {jsonl_file}\n         {out_file}")


if __name__ == "__main__":
    main()

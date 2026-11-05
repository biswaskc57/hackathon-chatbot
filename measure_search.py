"""Search quality only (no model calls, free, seconds): is the right passage in the top 1 / 3 / 5?

Run:  python3 measure_search.py              golden set: raw vs enriched vs enriched + glossary
      python3 measure_search.py --tickets    ALSO the blind ticket set: only for the final run, never while tuning
Golden misses are listed (development set). Tickets are a blind test (project brief), so they are off by default.
"""

import argparse
import csv
from pathlib import Path

from retrieval import DEFAULT_AIDS, DEFAULT_CORPUS, DEFAULT_GLOSSARY, BM25Index, load_corpus, load_glossary

DATA = Path(__file__).resolve().parent / "data"


def run(index, rows, question_of, list_misses):
    hits = {1: 0, 3: 0, 5: 0}
    misses = []
    for r in rows:
        gold = set(r["source_passage_ids"].split("|"))
        found = [p.id for p, _ in index.search(question_of(r), k=5)]
        for k in hits:
            hits[k] += bool(gold & set(found[:k]))
        if not gold & set(found[:3]):
            misses.append(r.get("question_id", ""))
    line = "  ".join(f"hit@{k} {v:>2}/{len(rows)}" for k, v in hits.items())
    return line + (f"   not in top 3: {', '.join(misses)}" if list_misses and misses else "")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aids", type=Path, default=DEFAULT_AIDS, help="customer-style questions file")
    parser.add_argument("--tickets", action="store_true", help="also report the blind ticket set (final run only)")
    args = parser.parse_args()

    golden = list(csv.DictReader(open(DATA / "golden_seed.csv", encoding="utf-8")))
    versions = {"raw": BM25Index(load_corpus(DEFAULT_CORPUS))}
    if args.aids.exists():
        versions["enriched"] = BM25Index(load_corpus(DEFAULT_CORPUS, args.aids))
        glossary = load_glossary(DEFAULT_GLOSSARY)
        if glossary:
            versions[f"+glossary({len(glossary)})"] = BM25Index(load_corpus(DEFAULT_CORPUS, args.aids), glossary=glossary)
    else:
        print(f"(no {args.aids.name} yet: run make_search_questions.py on the Mac first)")
    tickets = list(csv.DictReader(open(DATA / "tickets_tv.csv", encoding="utf-8"))) if args.tickets else []
    if tickets:
        print("BLIND TICKET RUN: report these numbers once; do not change search settings because of them.\n")
    for name, index in versions.items():
        print(f"{name:14} golden : {run(index, golden, lambda r: r['question'], True)}")
        if tickets:
            print(f"{name:14} tickets: {run(index, tickets, lambda r: r['subject'] + chr(10) * 2 + r['body'], False)}")


if __name__ == "__main__":
    main()

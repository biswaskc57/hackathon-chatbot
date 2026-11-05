"""Search quality only (no model calls, free, seconds): is the right passage in the top 1 / 3 / 5?

Run:  python3 measure_search.py              raw corpus vs enriched (if data/search_questions.jsonl exists)
Golden misses are listed (development set). Tickets are reported as totals only, so nobody tunes on them.
"""

import csv
import sys
from pathlib import Path

from retrieval import DEFAULT_AIDS, DEFAULT_CORPUS, BM25Index, load_corpus

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


def main(aids_path=DEFAULT_AIDS):
    golden = list(csv.DictReader(open(DATA / "golden_seed.csv", encoding="utf-8")))
    tickets = list(csv.DictReader(open(DATA / "tickets_tv.csv", encoding="utf-8")))
    versions = {"raw": BM25Index(load_corpus(DEFAULT_CORPUS))}
    if Path(aids_path).exists():
        versions["enriched"] = BM25Index(load_corpus(DEFAULT_CORPUS, aids_path))
    else:
        print(f"(no {aids_path.name} yet: run make_search_questions.py on the Mac first)")
    for name, index in versions.items():
        print(f"{name:9} golden : {run(index, golden, lambda r: r['question'], True)}")
        print(f"{name:9} tickets: {run(index, tickets, lambda r: r['subject'] + chr(10) * 2 + r['body'], False)}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_AIDS)

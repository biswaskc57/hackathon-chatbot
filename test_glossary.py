"""Check each glossary entry on our own test queries: does it help where it should, and not hurt elsewhere?

Test queries live in data/glossary_tests.csv (query, expected passages, which entry it tests, should help / must not hurt).
Write them from the manual or your own knowledge, never from the tickets. No model calls; runs in seconds.

Run:  python3 test_glossary.py
"""

import csv
from pathlib import Path

from retrieval import DEFAULT_AIDS, DEFAULT_CORPUS, BM25Index, entry_fires, expand_query, load_corpus, load_glossary

DATA = Path(__file__).resolve().parent / "data"


def best_rank(index, query, expected):
    ranked = [p.id for p, _ in index.search(query, k=len(index.passages))]
    ranks = [ranked.index(e) + 1 for e in expected if e in ranked]
    return min(ranks) if ranks else None


def main():
    glossary = load_glossary()
    passages = load_corpus(DEFAULT_CORPUS, DEFAULT_AIDS)
    without, with_g = BM25Index(passages), BM25Index(passages, glossary=glossary)
    tests = list(csv.DictReader(open(DATA / "glossary_tests.csv", encoding="utf-8")))
    print(f"{len(glossary)} glossary entries, {len(tests)} test queries (rank of the best expected passage; top 3 = sent to the model)\n")
    print(f"{'without':>7} {'with':>5}  {'result':10} {'kind':14} query  [entries that fired]")
    for t in tests:
        expected = t["expected_passages"].split("|")
        a, b = best_rank(without, t["query"], expected), best_rank(with_g, t["query"], expected)
        fired = [entry[1] for entry in glossary if entry_fires(entry, t["query"])]
        result = "better" if b < a else "WORSE" if b > a else "same"
        if a > 3 >= b: result = "FIXED"
        if b > 3 >= a: result = "BROKEN"
        print(f"{'#'+str(a):>7} {'#'+str(b):>5}  {result:10} {t['kind']:14} {t['query'][:60]}  {fired}")


if __name__ == "__main__":
    main()

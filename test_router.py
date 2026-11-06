"""Routing quality, no model calls, seconds: does the router answer, hand over or clarify when it should?

Test sets: data/golden_seed.csv (20 in-scope questions: all "answer") and data/extended_set.csv (our own set:
out of scope, trap passages, unclear, and in-scope questions with words like "return" or "order").
The ticket set is blind and is not used here.

Run:  python3 test_router.py
"""

import csv
from pathlib import Path

from router import route

DATA = Path(__file__).resolve().parent / "data"
LABELS = ("answer", "hand_over", "clarify")


def wilson(k: int, n: int, z: float = 1.96) -> str:
    """95% confidence interval for k out of n (Wilson), as 'a%–b%'."""
    if n == 0:
        return "–"
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / (1 + z * z / n)
    return f"{100 * max(0, centre - half):.0f}%–{100 * min(1, centre + half):.0f}%"


def main() -> None:
    rows = []
    for name in ("golden_seed.csv", "extended_set.csv"):
        with open(DATA / name, encoding="utf-8") as f:
            rows += [(name, r["question_id"], r["question"], r["expected_behaviour"]) for r in csv.DictReader(f)]

    matrix = {(e, g): 0 for e in LABELS for g in LABELS}
    misses = []
    for name, qid, question, expected in rows:
        got = route(question).route
        matrix[(expected, got)] += 1
        if got != expected:
            misses.append(f"  {qid}: expected {expected}, got {got}  ({question[:70]})")

    print(f"{len(rows)} questions (golden + extended). Rows: expected, columns: router decision\n")
    print(f"{'':12}" + "".join(f"{g:>11}" for g in LABELS))
    for e in LABELS:
        print(f"{e:12}" + "".join(f"{matrix[(e, g)]:>11}" for g in LABELS))

    tp = matrix[("hand_over", "hand_over")]
    predicted = sum(matrix[(e, "hand_over")] for e in LABELS)
    actual = sum(matrix[("hand_over", g)] for g in LABELS)
    wrong_handover = matrix[("answer", "hand_over")]
    answerable = sum(matrix[("answer", g)] for g in LABELS)
    print(f"\nHand-over precision {tp}/{predicted} ({wilson(tp, predicted)})   "
          f"recall {tp}/{actual} ({wilson(tp, actual)})")
    print(f"In-scope questions wrongly handed over: {wrong_handover}/{answerable} ({wilson(wrong_handover, answerable)})")
    correct = sum(matrix[(l, l)] for l in LABELS)
    print(f"All decisions correct: {correct}/{len(rows)} ({wilson(correct, len(rows))})")
    if misses:
        print("\nMisses:\n" + "\n".join(misses))


if __name__ == "__main__":
    main()

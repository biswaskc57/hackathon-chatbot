"""Find the manual passages that best match a customer question (keyword search, BM25).

BM25 ranks passages by the words they share with the question. Rare words (e.g. "Bluetooth")
count more than common ones (e.g. "TV"), and long passages are not favoured just for being long.

Used by assistant.py (answers) and the evaluation scripts (hit@k). No extra packages needed.
"""

import csv
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CORPUS = Path(__file__).resolve().parent / "data" / "corpus.jsonl"
DEFAULT_TOP_K = 3   # passages sent with each question
DEFAULT_AIDS = Path(__file__).resolve().parent / "data" / "search_questions.jsonl"  # customer-style questions (search only)
DEFAULT_GLOSSARY = Path(__file__).resolve().parent / "data" / "glossary.csv"  # customer words -> manual words (search only)

# A follow-up such as "I tried that but it didn't help" matches no passage well on its own. If the best score
# for the current message is below this, the search adds the customer's earlier messages. Measured on the
# golden questions: real questions score 9.8 or more, follow-ups 7.5 or less (raw and enriched search).
FOLLOW_UP_MAX_SCORE = 8.5
FOLLOW_UP_EARLIER_MESSAGES = 2

# Very common words that say nothing about the topic. "not", "no" are kept: they matter in symptoms.
STOPWORDS = set("""a an and are as at be but by can do does for from how i if in into is it its
me my of on or so that the then there this to was we what when where which while who why will
with you your our us i'm it's""".split())


@dataclass
class Passage:
    id: str
    title: str
    text: str          # full original text, title included, exactly as in the corpus
    category: str
    kind: str
    origin: str
    search_aids: tuple = ()   # extra words for SEARCH only (customer-style questions); never sent as answer text

    @property
    def search_text(self) -> str:
        return " ".join((self.text,) + tuple(self.search_aids))


def split_title(text: str) -> str:
    """Every passage starts with its title followed by '. ' (e.g. 'Choosing a picture mode. ...')."""
    return text.split(". ", 1)[0].strip()


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [w for w in words if w not in STOPWORDS]


def load_glossary(path: Path = DEFAULT_GLOSSARY) -> list[tuple]:
    """Rows of glossary.csv -> [(regex matching any customer term, manual terms to add)]."""
    if not Path(path).exists():
        return []
    entries = []
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            terms = [t.strip().lower() for t in (row.get("customer_terms") or "").split(";") if t.strip()]
            manual = (row.get("manual_terms") or "").strip()
            if terms and manual:
                pattern = re.compile(r"\b(" + "|".join(re.escape(t) for t in terms) + r")\b", re.I)
                entries.append((pattern, manual))
    return entries


def expand_query(query: str, glossary: list[tuple]) -> str:
    """Add the manual's words for every glossary term found. The customer's own words are kept."""
    extra = [manual for pattern, manual in glossary if pattern.search(query)]
    return query + (" " + " ".join(extra) if extra else "")


class BM25Index:
    def __init__(self, passages: list[Passage], k1: float = 1.5, b: float = 0.75, glossary: list[tuple] | None = None):
        self.passages = passages
        self.glossary = glossary or []
        self.k1, self.b = k1, b
        self.docs = [Counter(tokenize(p.search_text)) for p in passages]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avg_length = sum(self.lengths) / len(self.lengths)
        doc_freq = Counter(word for d in self.docs for word in d)
        n = len(passages)
        self.idf = {w: math.log(1 + (n - df + 0.5) / (df + 0.5)) for w, df in doc_freq.items()}

    def search(self, query: str, k: int = 3) -> list[tuple[Passage, float]]:
        terms = tokenize(expand_query(query, self.glossary))
        scores = []
        for p, doc, length in zip(self.passages, self.docs, self.lengths):
            score = 0.0
            for t in terms:
                tf = doc.get(t, 0)
                if tf:
                    score += self.idf[t] * tf * (self.k1 + 1) / (
                        tf + self.k1 * (1 - self.b + self.b * length / self.avg_length))
            scores.append((p, score))
        scores.sort(key=lambda x: x[1], reverse=True)
        return [(p, s) for p, s in scores[:k] if s > 0]


def search_turn(index: BM25Index, text: str, earlier: list[str], k: int = DEFAULT_TOP_K,
                follow_up: bool = True) -> tuple[list[Passage], bool]:
    """Passages for one customer message; earlier = the customer's earlier messages, oldest first.

    Returns (passages, used_earlier). A new question is searched on its own, so a change of topic is not
    mixed with the old one. A weak match (a follow-up) is searched together with the last earlier messages,
    unless follow_up is False.
    """
    hits = index.search(text, k=k)
    if follow_up and earlier and (not hits or hits[0][1] < FOLLOW_UP_MAX_SCORE):
        query = " ".join(earlier[-FOLLOW_UP_EARLIER_MESSAGES:] + [text])
        return [p for p, _ in index.search(query, k=k)], True
    return [p for p, _ in hits], False


def load_aids(path: Path) -> dict:
    """passage id -> list of customer-style questions."""
    if not Path(path).exists():
        raise FileNotFoundError(
            f"{path} not found. Create it first on the Mac: .venv/bin/python make_search_questions.py")
    with open(path, encoding="utf-8") as f:
        return {r["id"]: r["questions"] for r in map(json.loads, filter(str.strip, f))}


def load_corpus(path: Path = DEFAULT_CORPUS, aids_path: Path | None = None) -> list[Passage]:
    """Load the passages. With aids_path, attach customer-style questions to each passage's search text."""
    if not Path(path).exists():
        # Stop instead of answering without the manual: that is the mode that invents features.
        raise FileNotFoundError(
            f"Manual corpus not found at {path}. Copy the organisers' corpus.jsonl into data/.")
    passages = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                passages.append(Passage(r["id"], split_title(r["text"]), r["text"],
                                        r["category"], r["kind"], r["origin"]))
    if aids_path is not None:
        aids = load_aids(aids_path)
        passages = [Passage(p.id, p.title, p.text, p.category, p.kind, p.origin, tuple(aids.get(p.id, ())))
                    for p in passages]
    return passages


_indexes: dict = {}


def get_index(search_questions: bool = False, glossary: bool = False, path: Path = DEFAULT_CORPUS) -> BM25Index:
    """Build each search variant once and reuse it (the Settings fields of the same names choose it)."""
    key = (str(path), search_questions, glossary)
    if key not in _indexes:
        _indexes[key] = BM25Index(load_corpus(path, DEFAULT_AIDS if search_questions else None),
                                  glossary=load_glossary() if glossary else None)
    return _indexes[key]


if __name__ == "__main__":
    # Quick try:  python3 retrieval.py "my remote does nothing"
    import sys
    question = " ".join(sys.argv[1:]) or "Which picture mode is the easiest on the eyes?"
    for p, score in get_index().search(question, k=5):
        print(f"{score:6.2f}  {p.id}  {p.title}")

"""Menu-path check (R2): every menu path in an answer must exist in the manual. Switch: settings.menu_check.

A path such as "Settings > Picture > Picture Mode > Natural" is accepted when the manual has the whole path, or
has the path without its last step and names that last step in the same passage (an option of that menu, e.g.
"Natural" in the Picture Mode passage). The manual writes paths both with and without ">", so both sides are
compared without arrows, bold marks or case.

When a path is not found, run_turn blocks the answer and hands over: a missing answer is better than a setting
that does not exist ("a confident wrong answer is worse than a hand-over").
"""

import json
import re
from functools import lru_cache
from pathlib import Path

CORPUS = Path(__file__).resolve().parent / "data" / "corpus.jsonl"

# Two or more steps joined by ">". A step is capitalised words ("Picture Mode", "Anynet+ (HDMI-CEC)"), with small
# joining words inside ("Power On with Mobile"); the sentence after the path ("has not changed") is not part of it.
WORD = r"[A-Z0-9(][\w+&'’/()-]*"
JOIN = r"(?:on|off|with|of|for|the|to|&)"
SEGMENT = rf"{WORD}(?: (?:{WORD}|{JOIN}(?= [A-Z0-9(])))*"
MENU_PATH = re.compile(rf"{SEGMENT}(?:\s*>\s*{SEGMENT})+")

BLOCK_MESSAGE = ("I couldn't confirm that menu in the Smart Tech manual, so I won't guess a setting that may not "
                 "exist. I've passed your question to a colleague, who will get back to you.")


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[>*\"“”]", " ", text)).strip().lower()


@lru_cache(maxsize=1)
def passages() -> tuple[str, ...]:
    with CORPUS.open(encoding="utf-8") as f:
        return tuple(normalise(json.loads(line)["text"]) for line in f if line.strip())


def menu_paths(answer: str) -> list[str]:
    text = answer.replace("**", "").replace("`", "")
    paths = []
    for m in MENU_PATH.finditer(text):
        steps = [s.strip() for s in m.group(0).split(">")]
        steps[0] = steps[0].split()[-1]   # "Go to Settings" -> "Settings": only the menu word starts the path
        paths.append(" > ".join(steps))
    return list(dict.fromkeys(paths))


def path_known(path: str) -> bool:
    # Notes are not menu names: "Signal Information (digital channels only)", "Auto Update on/off".
    cleaned = re.sub(r"\([^)]*\)?|\bon/off\b", " ", path)
    steps = [normalise(s) for s in cleaned.split(">") if normalise(s)]
    whole = " ".join(steps)
    if any(whole in p for p in passages()):
        return True
    if len(steps) > 2:   # last step may be an option named in the passage of its menu
        prefix, last = " ".join(steps[:-1]), steps[-1]
        return any(prefix in p and re.search(rf"\b{re.escape(last)}\b", p) for p in passages())
    return False


def check(answer: str) -> tuple[list[str], list[str]]:
    """Return (paths found, paths not in the manual)."""
    found = menu_paths(answer)
    return found, [p for p in found if not path_known(p)]


if __name__ == "__main__":
    import sys
    print(check(" ".join(sys.argv[1:]) or "Go to Settings > Picture > Picture Mode > Natural, or Settings > Picture > Eye Comfort."))

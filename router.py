"""Scope router (R2, v1): answer | hand_over | clarify. Switch: settings.router.

Rules, no model call: fast, free, the same every time, and measurable offline (test_router.py).
- hand_over: the message needs the customer's own order, contract, payment or a technician: warranty, repair or
  physical damage, orders and delivery, returns and refunds, prices and buying, billing. These go to a human with a
  ticket; the bot does not answer them (this also keeps the trap passages p0020 and p0138 from being used).
- clarify: the first message is too short to know what the customer means ("help", "tv broken").
- answer: everything else goes to search and the answer model.

Known limits: a message that mixes a TV question with a warranty question is handed over as a whole (the e-mail
drafter answers the TV part). Safety cases ("burning smell") are handed over without the manual's safety steps.
A model-based router is the next step if the rules miss too much on the extended set.
"""

import re
from dataclasses import dataclass

from retrieval import tokenize

# (category, pattern). Whole words, any case. Written from the brief's out-of-scope list and general knowledge,
# never from tickets.
OUT_OF_SCOPE = [
    ("Warranty", r"warrant(y|ies)|guarantee|garantie"),
    ("Repair", r"repair|technician|service (appointment|visit|centre|center)|request (service|support)"
               r"|crack(ed)?|smashed|shattered|physical(ly)? damage|burning smell|smoke"),
    ("Orders", r"my order|order (number|status)|ordered|deliver(y|ed)|shipping|shipped|tracking number|parcel"),
    ("Returns", r"refund|send (it|the tv) back|return (it|the tv|my tv)|money back|cancel (my|the) (order|purchase)"),
    ("Prices", r"price|how much (is|does|do|are)|cost(s)? of|discount|buy (a|an|the|new|another|spare)|purchase"),
    ("Account and billing", r"billing|invoice|charged|payment|subscription fee"),
]
OUT_RE = [(cat, re.compile(r"\b(" + pat + r")\b", re.I)) for cat, pat in OUT_OF_SCOPE]
MIN_WORDS = 3   # a first message with fewer topic words than this gets one clarifying question

CLARIFY_QUESTION = ("I'd like to help. Could you tell me a bit more: what are you trying to do on the TV, "
                    "or what do you see on the screen?")


def hand_over_message(category: str) -> str:
    return (f"That's a question for my human colleagues ({category.lower()}), so I won't guess. "
            "I've passed your request on with a summary, and a colleague will contact you. "
            "Is there anything about using your TV I can help with in the meantime?")


@dataclass
class Route:
    route: str      # answer | hand_over | clarify
    category: str   # out-of-scope category, or ""
    reason: str     # one line for the trace


def route(text: str, is_follow_up: bool = False) -> Route:
    for category, pattern in OUT_RE:
        m = pattern.search(text)
        if m:
            return Route("hand_over", category, f'Out of scope ({category}): "{m.group(0)}"')
    words = tokenize(text)
    if not is_follow_up and len(words) < MIN_WORDS:
        return Route("clarify", "", f"Too short to know what is meant ({len(words)} topic words)")
    return Route("answer", "", "In scope: TV how-to or troubleshooting")

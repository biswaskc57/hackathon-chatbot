"""Mask personal data before any text goes to the model (GDPR). Switch: settings.pii_mask.

Regex only, no model call: e-mail addresses, serial and order numbers, phone numbers, street addresses and names
that the customer introduces ("my name is ..."). The customer still sees their own message; the model, the
history sent with later turns and the ticket summary get the masked text.

Known limits: names without an introduction ("Anna here") and free-form addresses are not found.
E-mail drafting (email_draft.clean_email) keeps its own clean-up, which also removes quoted replies and sign-offs.
"""

import re

EMAIL_ADDR = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
# The number must contain a digit, so "serial number is broken" or an earlier "[serial number]" is left alone.
SERIAL = re.compile(r"\b(serial(?: number| no\.?)?|s/n)\s*(?:is\s*)?[:#]?\s*(?=[A-Z0-9-]*\d)[A-Z0-9][A-Z0-9-]{4,}", re.I)
ORDER = re.compile(r"\border (?:number|no\.?|#)\s*(?:is\s*)?[:#]?\s*(?=[A-Z0-9-]*\d)[A-Z0-9][A-Z0-9-]{3,}", re.I)
PHONE = re.compile(r"(?<!\w)\+?\d[\d ()./-]{7,}\d")
ADDRESS = re.compile(r"\b[A-ZÄÖÜ][\wäöüß.-]*(?:straße|strasse|street|road|avenue|weg|gasse|allee|platz)\s+\d+\w?\b"
                     r"|\b\d+\s+[A-Z][\w.-]*\s+(?:Street|St\.|Road|Rd\.|Avenue|Ave\.|Lane)\b")
NAME = re.compile(r"\b(my name is|name\s*:)\s+[A-ZÄÖÜ][\wäöüß-]+(?:\s+[A-ZÄÖÜ][\wäöüß-]+)?", re.I)

# Order matters: e-mail addresses contain digits a phone pattern could take.
PATTERNS = (
    (EMAIL_ADDR, "[e-mail address]", None),
    (SERIAL, "[serial number]", None),
    (ORDER, "[order number]", None),
    (PHONE, "[phone number]", None),
    (ADDRESS, "[address]", None),
    (NAME, "[name]", lambda m: f"{m.group(1)} [name]"),
)


PLACEHOLDER = re.compile(r"\[(?:e-mail address|serial number|order number|phone number|address|name)\]")


def for_search(masked: str) -> str:
    """The masked text without placeholders, so words like "phone number" do not steer the manual search."""
    return re.sub(r"\s+", " ", PLACEHOLDER.sub(" ", masked)).strip()


def mask(text: str) -> tuple[str, list[str]]:
    """Return (masked text, labels of what was masked, e.g. ['e-mail address', 'serial number'])."""
    found = []
    for pattern, label, keep in PATTERNS:
        if pattern.search(text):
            found.append(label.strip("[]"))
            text = pattern.sub(keep or label, text)
    return text, found


if __name__ == "__main__":
    import sys
    print(mask(" ".join(sys.argv[1:]) or
               "My name is Jan Kowalski, serial number ST55-88421X, jan@example.com, +49 151 2345 6789, Hauptstraße 5"))

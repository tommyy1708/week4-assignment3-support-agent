"""The Data Masker's rule (K-2): replace PII that isn't the customer's own, and change nothing
else: no case, no whitespace, no punctuation (SPEC §11 R-8, the lowercase Masker).

"The customer's own" (decision A) = their login email, plus any email or phone number they
wrote in this turn's message: they told us, so echoing it back is not a leak."""

import re

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?<![\w-])(?:\+?\d{1,2}[ .-]?)?(?:\(\d{3}\)[ .-]?|\d{3}[ .-])?\d{3}[ .-]\d{4}(?![\w-])")
CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")

KINDS = (  # checked in this order, so a card number isn't half-masked as a phone
    ("card number", CARD, "[card number removed]"),
    ("email", EMAIL, "[email removed]"),
    ("phone number", PHONE, "[phone number removed]"),
)


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def mask(text: str, user_email: str, user_message: str = "") -> tuple[str, dict[str, int]]:
    """Return (masked_text, {kind: count}). Only matched spans are touched."""
    own_emails = {user_email.lower()} | {e.lower() for e in EMAIL.findall(user_message)}
    own_phones = {_digits(p) for p in PHONE.findall(user_message)}
    counts = {kind: 0 for kind, _, _ in KINDS}

    for kind, pattern, label in KINDS:
        def replace(m: re.Match) -> str:
            value = m.group(0)
            if kind == "email" and value.lower() in own_emails:
                return value
            if kind == "phone number" and _digits(value) in own_phones:
                return value
            counts[kind] += 1
            return label
        text = pattern.sub(replace, text)
    return text, counts


def describe(counts: dict[str, int]) -> str:
    """K-3: say what was masked, or that there was nothing to mask."""
    parts = [f"{n} {kind}{'s' if n > 1 else ''}" for kind, n in counts.items() if n]
    return "masked " + ", ".join(parts) if parts else "nothing to mask"

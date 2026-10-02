"""The Sanitizer: the first guard, in-process and with no model call (S-1). A length limit, a
character allow-list, and only the most unmistakable patterns; the Judge does the real scan.
Apostrophes, # $ : ; @ and ordinary punctuation are allowed (S-2)."""

import re
import unicodedata

MAX_CHARS = 1000

# Control characters other than tab/newline, zero-width and bidi-override characters:
# invisible text is how instructions get smuggled past a human reading the log.
_INVISIBLE = {"​", "‌", "‍", "⁠", "﻿",
              "‪", "‫", "‬", "‭", "‮", "⁦", "⁧", "⁨", "⁩"}

_OBVIOUS = [
    ("script tag", re.compile(r"<\s*script\b", re.I)),
    ("SQL statement after a quote", re.compile(r"'\s*;\s*(drop|delete|update|insert|truncate|alter)\b", re.I)),
    ("UNION SELECT", re.compile(r"\bunion\s+(all\s+)?select\b", re.I)),
]


def sanitize(message: str) -> tuple[bool, str]:
    """Return (passed, detail)."""
    if len(message) > MAX_CHARS:
        return False, f"message too long ({len(message)} > {MAX_CHARS} characters)"
    for ch in message:
        if ch in _INVISIBLE or (unicodedata.category(ch) == "Cc" and ch not in "\t\n"):
            return False, f"disallowed character U+{ord(ch):04X}"
    for name, pattern in _OBVIOUS:
        if pattern.search(message):
            return False, f"blocked pattern: {name}"
    return True, f"{len(message)} chars, allowed characters, no obvious patterns"

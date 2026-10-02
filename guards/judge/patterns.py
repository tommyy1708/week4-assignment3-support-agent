"""The Judge's deterministic pattern scan (J-2): SQL injection, markup, template injection, shell
and path traversal, and prompt-extraction phrases. Each pattern needs attack syntax, not just a
scary word, so "drop the gift wrap", "select the fastest shipping" and "ignore my last message"
stay clean (T-LEGIT-FALSE-BLOCK)."""

import re

_I = re.IGNORECASE
PATTERNS: list[tuple[str, re.Pattern]] = [
    # SQL injection
    ("sql: quote then boolean", re.compile(r"'\s*(or|and)\s+'?\w+'?\s*=\s*'?\w+", _I)),
    ("sql: numeric tautology", re.compile(r"\b(or|and)\s+(\d+)\s*=\s*\2\b", _I)),
    ("sql: quoted tautology", re.compile(r"'(\w+)'\s*=\s*'\1'", _I)),
    ("sql: UNION SELECT", re.compile(r"\bunion\s+(all\s+)?select\b", _I)),
    ("sql: stacked statement", re.compile(r";\s*(drop|delete|update|insert|alter|truncate|create)\b", _I)),
    ("sql: DDL", re.compile(r"\b(drop|truncate|alter)\s+table\b", _I)),
    ("sql: SELECT … FROM", re.compile(r"\bselect\s+[\w*,\s]+?\s+from\s+\w+", _I)),
    ("sql: DELETE FROM / UPDATE SET", re.compile(r"\bdelete\s+from\b|\bupdate\s+\w+\s+set\b", _I)),
    ("sql: comment after quote", re.compile(r"'\s*--")),
    ("sql: LIKE wildcard", re.compile(r"\blike\s+'%", _I)),
    # Markup and script
    ("markup: HTML tag", re.compile(r"<\s*/?\s*(script|iframe|img|svg|object|embed|link|style|body)\b", _I)),
    ("markup: event handler", re.compile(r"\bon[a-z]+\s*=", _I)),
    ("markup: javascript URL", re.compile(r"javascript\s*:", _I)),
    # Template injection
    ("template: {{ }} / ${ } / {% %}", re.compile(r"\{\{.*?\}\}|\$\{.*?\}|\{%.*?%\}")),
    # Shell and path traversal
    ("shell: command substitution", re.compile(r"\$\(|`[^`]+`")),
    ("shell: chained command", re.compile(r";\s*(cat|rm|ls|curl|wget|bash|sh|nc|chmod)\b", _I)),
    ("shell: rm -rf", re.compile(r"\brm\s+-rf\b", _I)),
    ("path traversal", re.compile(r"\.\./|/etc/(passwd|shadow)\b", _I)),
    # Prompt injection and extraction
    ("prompt: ignore previous",
     re.compile(r"\bignore\s+(all\s+)?(the\s+|your\s+)?(previous|prior|above|earlier)\b", _I)),
    ("prompt: forget rules", re.compile(r"\bforget\s+(all\s+)?(your|the)\s+(rules|instructions)\b", _I)),
    ("prompt: role override", re.compile(r"\byou\s+are\s+now\b|^\s*system\s*:", _I)),
    ("prompt: new instructions", re.compile(r"#{2,}\s*(new\s+)?instructions\b", _I)),
    ("prompt: system prompt", re.compile(r"\bsystem\s+prompt\b", _I)),
    ("prompt: reveal instructions", re.compile(
        r"\b(print|show|reveal|repeat|quote|output)\s+(me\s+)?(your|the)\s+(instructions|rules|prompt)\b"
        r"|\brepeat\s+everything\s+above\b|\bwhat\s+were\s+you\s+told\b", _I)),
    ("prompt: dump data", re.compile(r"\bdump\s+(the\s+)?(customer_orders|users|database|table|orders)\b", _I)),
]


def scan(message: str) -> list[str]:
    """Names of every pattern the message matches; empty means clean."""
    return [name for name, pattern in PATTERNS if pattern.search(message)]

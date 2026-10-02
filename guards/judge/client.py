"""The pipeline's side of the Judge: one A2A call, and a strict parse of its verdict. Anything
but a valid {verdict, reason} raises GuardError; nothing here can return "allow" by accident (J-4)."""

import os

from pydantic import ValidationError

from guards.a2a import GuardError, send_text
from guards.judge.verdict import Verdict, parse_verdict

JUDGE_URL = os.getenv("JUDGE_URL", "http://127.0.0.1:10002/")


async def judge(message: str) -> tuple[Verdict, int, int]:
    """Return (verdict, tokens_in, tokens_out); tokens are 0 when the pattern scan decided."""
    text, metadata = await send_text(JUDGE_URL, message, "Security Judge")
    usage = metadata.get("adk_usage_metadata") or {}
    try:
        verdict = parse_verdict(text)
    except (ValueError, ValidationError) as e:
        raise GuardError(f"Security Judge verdict unparseable: {text[:200]!r}") from e
    return verdict, int(usage.get("promptTokenCount", 0)), int(usage.get("candidatesTokenCount", 0))

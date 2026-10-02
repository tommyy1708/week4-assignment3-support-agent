"""The pipeline's side of the Judge: one A2A message/send call. Every way this can fail
(unreachable, timeout, JSON-RPC error, no verdict, unparseable verdict) raises GuardError,
which the pipeline turns into an error event; nothing here can return "allow" by accident (J-4)."""

import os
import uuid

import httpx
from pydantic import ValidationError

from guards.judge.verdict import Verdict, parse_verdict

JUDGE_URL = os.getenv("JUDGE_URL", "http://127.0.0.1:10002/")
TIMEOUT_S = 15


class GuardError(Exception):
    """A guard could not give a verdict. Fail loud: the turn ends with an error (P-4)."""


async def judge(message: str) -> tuple[Verdict, int, int]:
    """Return (verdict, tokens_in, tokens_out); tokens are 0 when the pattern scan decided."""
    payload = {
        "jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": "message/send",
        "params": {"message": {"role": "user", "messageId": uuid.uuid4().hex,
                               "parts": [{"kind": "text", "text": message}]}},
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            response = await client.post(JUDGE_URL, json=payload)
            response.raise_for_status()
            body = response.json()
    except (httpx.HTTPError, ValueError) as e:
        raise GuardError(f"Security Judge unreachable: {type(e).__name__}: {e}") from e
    if "error" in body:
        raise GuardError(f"Security Judge returned an error: {body['error'].get('message')}")
    result = body.get("result") or {}
    text = _reply_text(result)
    usage = (result.get("metadata") or {}).get("adk_usage_metadata") or {}
    try:
        return parse_verdict(text), int(usage.get("promptTokenCount", 0)), int(usage.get("candidatesTokenCount", 0))
    except (ValueError, ValidationError) as e:
        raise GuardError(f"Security Judge verdict unparseable: {text[:200]!r}") from e


def _reply_text(result: dict) -> str:
    """The agent's text from a Task (artifacts, else status message) or a Message."""
    if result.get("kind") == "task":
        parts = [p for a in result.get("artifacts") or [] for p in a.get("parts", [])]
        parts = parts or ((result.get("status") or {}).get("message") or {}).get("parts", [])
    else:
        parts = result.get("parts", [])
    return "".join(p.get("text", "") for p in parts if p.get("kind") == "text")

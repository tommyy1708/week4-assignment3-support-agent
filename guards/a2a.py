"""Calling a guard service over A2A (JSON-RPC message/send). Every way a call can fail
(unreachable, timeout, JSON-RPC error, empty reply) raises GuardError, and the pipeline turns
that into an error event: a guard failure is never read as a pass (P-4, J-4)."""

import uuid

import httpx

TIMEOUT_S = 15


class GuardError(Exception):
    """A guard could not give an answer. Fail loud: the turn ends with an error (P-4)."""


async def send_text(url: str, text: str, service: str) -> tuple[str, dict]:
    """Send one text message; return (the agent's reply text, the task's metadata)."""
    payload = {
        "jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": "message/send",
        "params": {"message": {"role": "user", "messageId": uuid.uuid4().hex,
                               "parts": [{"kind": "text", "text": text}]}},
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            body = response.json()
    except (httpx.HTTPError, ValueError) as e:
        raise GuardError(f"{service} unreachable: {type(e).__name__}: {e}") from e
    if "error" in body:
        raise GuardError(f"{service} returned an error: {body['error'].get('message')}")
    result = body.get("result") or {}
    reply = _reply_text(result)
    if not reply:
        raise GuardError(f"{service} sent an empty reply")
    return reply, result.get("metadata") or {}


def _reply_text(result: dict) -> str:
    """The agent's text from a Task (artifacts, else status message) or a Message."""
    if result.get("kind") == "task":
        parts = [p for a in result.get("artifacts") or [] for p in a.get("parts", [])]
        parts = parts or ((result.get("status") or {}).get("message") or {}).get("parts", [])
    else:
        parts = result.get("parts", [])
    return "".join(p.get("text", "") for p in parts if p.get("kind") == "text")

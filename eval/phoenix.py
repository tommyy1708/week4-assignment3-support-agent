"""Read spans back from Phoenix over REST (EVALS §7), grouped by trace id."""

import os

import httpx

PHOENIX_URL = os.getenv("PHOENIX_URL", "http://127.0.0.1:6006")
PROJECT = "support-desk"

# SPEC §10: the spans a turn that passed every guard must contain (invoke_agent matched by prefix).
REQUIRED = ["agent.turn", "security.sanitize", "security.a2a_judge", "guardrail.check",
            "memory.recall", "invoke_agent", "security.a2a_mask", "memory.save"]


def spans_by_trace(since_iso: str) -> dict[str, list[dict]]:
    """Every span in the project that started after `since_iso`, paginated."""
    by_trace: dict[str, list[dict]] = {}
    cursor = None
    with httpx.Client(timeout=30) as client:
        while True:
            params = {"limit": 1000, "start_time": since_iso} | ({"cursor": cursor} if cursor else {})
            body = client.get(f"{PHOENIX_URL}/v1/projects/{PROJECT}/spans", params=params).raise_for_status().json()
            for span in body["data"]:
                by_trace.setdefault(span["context"]["trace_id"], []).append(span)
            cursor = body.get("next_cursor")
            if not cursor:
                return by_trace


def names(spans: list[dict]) -> set[str]:
    return {s["name"] for s in spans}


def has(spans: list[dict], name: str) -> bool:
    return any(s["name"] == name or s["name"].startswith(name + " ") for s in spans)


def roots(spans: list[dict]) -> list[dict]:
    """agent.turn spans with no parent: exactly one per turn (T-TRACE-ONE)."""
    return [s for s in spans if s["name"] == "agent.turn" and not s.get("parent_id")]


def missing_required(spans: list[dict]) -> list[str]:
    return [n for n in REQUIRED if not has(spans, n)]

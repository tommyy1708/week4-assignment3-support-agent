"""Pure checks the runner applies: the "contains" rule, percentiles and the event-stream
ordering rules of SPEC §7.3. Arithmetic only; no model decides a pass (EVALS §1, rule E3)."""

import math

ORDER = ["sanitize", "judge", "guardrail", "recall", "agent", "mask", "save"]
AGENT_EVENTS = {"llm", "tool_call", "tool_result"}


def norm(text: str) -> str:
    """EVALS §3: case-insensitive, after removing $ and , from both sides."""
    return str(text).lower().replace("$", "").replace(",", "")


def contains(haystack: str, needle: str) -> bool:
    return norm(needle) in norm(haystack)


def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile; None for an empty list."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(p * len(ordered)) - 1)]


def event_order_violations(events: list[dict]) -> list[str]:
    """Every SPEC §7.3 rule the stream breaks; empty means it obeys all six."""
    v = []
    if not events or events[0].get("type") != "trace":
        v.append("1: trace is not the first event")
    terminals = [i for i, e in enumerate(events) if e.get("type") in ("final", "error")]
    if len(terminals) != 1 or terminals[0] != len(events) - 1:
        v.append("5: not exactly one terminal event, last")

    open_stage, last_index, calls, results = None, -1, {}, {}
    for i, e in enumerate(events):
        kind = e.get("type")
        if kind == "stage":
            if open_stage is not None:
                v.append(f"2: stage {e['key']} began before step {open_stage}")
            index = ORDER.index(e["key"]) if e["key"] in ORDER else -1
            if index <= last_index:
                v.append(f"2: stage {e['key']} out of order")
            open_stage, last_index = e["key"], index
        elif kind == "step":
            if e.get("key") != open_stage:
                v.append(f"2: step {e.get('key')} without its stage")
            open_stage = None
            if e.get("status") == "blocked":
                nxt = events[i + 1] if i + 1 < len(events) else {}
                if not (nxt.get("type") == "final" and nxt.get("blocked") and nxt.get("blocked_at") == e["key"]):
                    v.append("4: a blocked step is not followed by final{blocked} with the same blocked_at")
        elif kind in AGENT_EVENTS:
            if open_stage != "agent":
                v.append(f"2: {kind} outside the agent stage")
            if kind == "tool_call":
                calls[e["id"]] = calls.get(e["id"], 0) + 1
            if kind == "tool_result":
                results[e["id"]] = results.get(e["id"], 0) + 1
    if any(results.get(cid) != 1 for cid in calls) or any(rid not in calls for rid in results):
        v.append("3: a tool_call without exactly one tool_result of the same id")

    end = events[-1] if events else {}
    stopped = end.get("type") == "error" or (end.get("type") == "final" and end.get("blocked"))
    if stopped and end.get("step") != "save" and any(e.get("key") == "save" for e in events):
        v.append("6: save appears on a blocked or error turn")
    if end.get("type") == "final" and end.get("blocked"):
        blocked_at = next((i for i, e in enumerate(events) if e.get("status") == "blocked"), len(events))
        if any(e.get("type") in AGENT_EVENTS or e.get("key") in ("recall", "save") for e in events[blocked_at + 1:]):
            v.append("4: agent, recall or save events after a block")
    return v

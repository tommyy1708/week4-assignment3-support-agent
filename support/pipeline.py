"""One support turn as a stream of events (SPEC §7.1). The CLI and the web server only render
this stream; no pipeline logic lives in either (P-1).

Each turn runs inside one root span, agent.turn (O-2).
Fixed order (P-2): sanitize -> judge -> guardrail -> recall -> agent -> mask -> save.
A guard that blocks ends the turn at once (P-3); a guard that fails ends it with an error (P-4).
Every step after the agent runs only on turns that were not blocked, so a blocked message is
never remembered."""

import asyncio
import json
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from openinference.semconv.trace import OpenInferenceSpanKindValues, SpanAttributes
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from toolbox_core import ToolboxClient

from guards import guardrail
from guards.judge.client import judge
from guards.masker.client import mask_reply
from guards.sanitizer import sanitize
from support import memory
from support.agent import MODEL, build_agent
from support.telemetry import trace_url
from support.tool_info import tool_info

APP_NAME = "support_desk"
RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"

# Per-turn budget (THRESHOLDS §6). Hitting one ends the turn with terminated: "cap" (P-6).
T_BUD_TOOLS = 6
T_BUD_TOKENS = 30_000
T_BUD_WALL_S = 30

BLOCKED_REPLY = "Sorry, I can't help with that request."

_tracer = trace.get_tracer("support.pipeline")


@dataclass
class SupportSession:
    """One logged-in customer: their agent (email already bound) and ADK session."""
    customer: dict
    runner: Runner
    session_id: str


async def open_session(client: ToolboxClient, customer: dict) -> SupportSession:
    agent = await build_agent(client, customer)
    sessions = InMemorySessionService()
    session = await sessions.create_session(app_name=APP_NAME, user_id=customer["email"])
    runner = Runner(app_name=APP_NAME, agent=agent, session_service=sessions)
    return SupportSession(customer, runner, session.id)


@dataclass
class GuardResult:
    passed: bool
    detail: str
    tokens_in: int = 0
    tokens_out: int = 0
    output: str | None = None  # text the step hands on: the Masker's masked reply, recall's agent input
    event_extra: dict = field(default_factory=dict)       # extra fields on the step event (recall's memories)
    log_extra: dict = field(default_factory=dict)         # extra fields in the run log's step entry
    span_attributes: dict = field(default_factory=dict)


async def _check_sanitize(message: str) -> GuardResult:
    return GuardResult(*sanitize(message))


async def _check_judge(message: str) -> GuardResult:
    verdict, tokens_in, tokens_out = await judge(message)
    return GuardResult(verdict.verdict == "allow", f"{verdict.verdict}: {verdict.reason}", tokens_in, tokens_out)


async def _check_guardrail(message: str) -> GuardResult:
    decision, tokens_in, tokens_out = await guardrail.check(message)
    return GuardResult(decision.decision == "safe", f"{decision.decision}: {decision.reasoning}", tokens_in, tokens_out)


@dataclass(frozen=True)
class _Guard:
    key: str
    label: str
    span: str
    kind: str
    check: Callable[[str], Awaitable[GuardResult]]
    span_kind: str = OpenInferenceSpanKindValues.GUARDRAIL.value
    blocked_reply: str = BLOCKED_REPLY
    error_note: str = "Your message could not be checked, so it was not answered."


# The inbound guards, in order (P-2). Recall, mask and save are built per turn below.
GUARDS = (
    _Guard("sanitize", "Sanitizer", "security.sanitize", "in-process", _check_sanitize),
    _Guard("judge", "A2A Security Judge", "security.a2a_judge", "A2A", _check_judge),
    _Guard("guardrail", "Guardrail", "guardrail.check", "in-process", _check_guardrail,
           blocked_reply=guardrail.BLOCKED_REPLY),
)


def _mask_guard(turn: "_Turn", user_message: str) -> _Guard:
    """The outbound guard (K-1..K-3): never blocks, returns the reply with other people's PII masked."""
    async def check(text: str) -> GuardResult:
        masked, detail = await mask_reply(text, turn.user, user_message)
        return GuardResult(True, detail, output=masked)
    return _Guard("mask", "A2A Data Masker", "security.a2a_mask", "A2A", check,
                  error_note="The reply could not be checked for personal data, so it was not sent.")


def _recall_step(turn: "_Turn") -> _Guard:
    """Recall is a step, not a tool (R-1): search Mem0, report every candidate, hand the agent its input."""
    async def check(message: str) -> GuardResult:
        candidates = await memory.recall(turn.user, message)
        inserted = sum(c["inserted"] for c in candidates)
        attributes = {}
        for i, c in enumerate(candidates):  # RETRIEVER span: each document's content and score
            prefix = f"retrieval.documents.{i}.document"
            attributes[f"{prefix}.content"] = c["memory"]
            attributes[f"{prefix}.score"] = c["score"]
            attributes[f"{prefix}.metadata"] = json.dumps({"inserted": c["inserted"], "reason": c["reason"]})
        return GuardResult(
            True, f"{inserted} inserted, {len(candidates) - inserted} skipped",
            output=memory.with_memories(message, candidates),
            event_extra={"memories": candidates},
            log_extra={"inserted": inserted, "skipped": len(candidates) - inserted},
            span_attributes=attributes)
    return _Guard("recall", "Mem0 recall", "memory.recall", "Python fn", check,
                  span_kind=OpenInferenceSpanKindValues.RETRIEVER.value,
                  error_note="Memory recall failed, so the message was not answered.")


def _save_step(turn: "_Turn") -> _Guard:
    """Save is a step too: only the customer's own message, never the reply (R-4)."""
    async def check(message: str) -> GuardResult:
        status = await memory.save(turn.user, message)
        return GuardResult(True, f"saved the customer's message ({status})")
    return _Guard("save", "Mem0 save", "memory.save", "Python fn", check,
                  span_kind=OpenInferenceSpanKindValues.TOOL.value,
                  error_note="The memory could not be saved, so the turn was stopped.")


class _Cap(Exception):
    """A per-turn budget was hit; the argument names which one."""


class _Turn:
    """Everything the run log (EVALS §4.1) needs, collected while the turn runs."""

    def __init__(self, user: str, message: str):
        self.turn_id = f"turn_{time.strftime('%Y%m%dT%H%M%S')}_{secrets.token_hex(3)}"
        self.trace_id: str | None = None
        self.user, self.message = user, message
        self.t0 = time.monotonic()
        self.steps: list[dict] = []
        self.tool_calls: list[dict] = []
        self.pending: dict[str, dict] = {}  # ADK call id -> tool_call event awaiting its result
        self.llm_calls = 0
        self.tokens = {"in": 0, "out": 0}

    def ms(self) -> int:
        return int((time.monotonic() - self.t0) * 1000)

    def write_log(self, terminated: str, blocked_at: str | None = None) -> None:
        RUNS_DIR.mkdir(exist_ok=True)
        log = {
            "turn_id": self.turn_id, "trace_id": self.trace_id, "user": self.user, "message": self.message,
            "terminated": terminated, "blocked_at": blocked_at, "wall_clock_ms": self.ms(),
            "tokens": self.tokens, "steps": self.steps, "tool_calls": self.tool_calls,
            "llm_calls": self.llm_calls,
        }
        (RUNS_DIR / f"{self.turn_id}.json").write_text(json.dumps(log, indent=2))


async def run_turn(sess: SupportSession, message: str) -> AsyncIterator[dict]:
    """Run one turn inside its agent.turn span. ADK runs in this same task and context, so its
    invoke_agent span becomes a child of agent.turn instead of a second root (T-TRACE-ONE)."""
    turn = _Turn(sess.customer["email"], message)
    attributes = {
        SpanAttributes.OPENINFERENCE_SPAN_KIND: OpenInferenceSpanKindValues.CHAIN.value,
        SpanAttributes.INPUT_VALUE: message,
        SpanAttributes.USER_ID: turn.user,
        "turn.id": turn.turn_id,
    }
    with _tracer.start_as_current_span("agent.turn", attributes=attributes) as span:
        turn.trace_id = format(span.get_span_context().trace_id, "032x")
        async for event in _turn_events(sess, turn, message):
            if event["type"] == "final":
                span.set_attribute(SpanAttributes.OUTPUT_VALUE, event["response"])
                span.set_attribute("turn.terminated", event["terminated"])
            elif event["type"] == "error":
                span.set_status(Status(StatusCode.ERROR, event["error"]))
                span.set_attribute("turn.terminated", "error")
            yield event


async def _turn_events(sess: SupportSession, turn: _Turn, message: str) -> AsyncIterator[dict]:
    yield {"type": "trace", "turn_id": turn.turn_id, "trace_id": turn.trace_id, "url": trace_url(turn.trace_id)}

    for guard in GUARDS:
        outcome = {"stop": False}
        async for event in _guard_events(turn, guard, message, outcome):
            yield event
        if outcome["stop"]:
            return

    outcome = {"stop": False}
    async for event in _guard_events(turn, _recall_step(turn), message, outcome):
        yield event
    if outcome["stop"]:
        return
    agent_input = outcome["output"]

    yield {"type": "stage", "key": "agent", "label": "Support agent"}
    started = time.monotonic()
    result: dict = {}
    terminated, response = "done", ""
    try:
        async for event in _agent_events(sess, turn, agent_input, result):
            yield event
        response = result.get("response", "")
    except (_Cap, TimeoutError) as cap:
        reason = str(cap) if isinstance(cap, _Cap) else "time"
        terminated = "cap"
        response = f"I had to stop here: this request went over the {reason} limit for one turn. Please try a simpler question."
        for event in _cancel_pending(turn, f"turn hit the {reason} limit"):
            yield event
    except Exception as e:  # Fail loud: an agent failure is an error, never a quiet empty answer (P-4).
        trace.get_current_span().record_exception(e)
        for event in _cancel_pending(turn, "turn failed"):
            yield event
        turn.write_log("error")
        yield {"type": "error", "step": "agent", "status": 502,
               "error": f"{type(e).__name__}: {e}", "terminated": "error"}
        return

    ms = int((time.monotonic() - started) * 1000)
    turn.steps.append({"key": "agent", "status": "passed", "ms": ms})
    yield {"type": "step", "key": "agent", "status": "passed",
           "detail": f"{turn.llm_calls} model calls, {len(turn.tool_calls)} tool calls",
           "ms": ms, "span": "invoke_agent support_agent", "kind": "in-process"}

    outcome = {"stop": False}
    async for event in _guard_events(turn, _mask_guard(turn, message), response, outcome):
        yield event
    if outcome["stop"]:
        return
    response = outcome["output"]

    outcome = {"stop": False}
    async for event in _guard_events(turn, _save_step(turn), message, outcome):
        yield event
    if outcome["stop"]:
        return

    turn.write_log(terminated)  # before the terminal event (P-5)
    yield {"type": "final", "blocked": False, "blocked_at": None, "response": response,
           "terminated": terminated, "wall_clock_ms": turn.ms(), "tokens": turn.tokens}


async def _guard_events(turn: _Turn, guard: _Guard, text: str, outcome: dict) -> AsyncIterator[dict]:
    """One pipeline step (a guard, recall, mask or save) in its own span, given `text`. Sets
    outcome["stop"] when the turn must end, and outcome["output"] to the text the step hands on.
    Any exception is an error event, never a pass (P-4)."""
    yield {"type": "stage", "key": guard.key, "label": guard.label}
    started = time.monotonic()
    error = None
    attributes = {SpanAttributes.OPENINFERENCE_SPAN_KIND: guard.span_kind, SpanAttributes.INPUT_VALUE: text}
    with _tracer.start_as_current_span(guard.span, attributes=attributes) as span:
        try:
            result = await guard.check(text)
            passed, detail = result.passed, result.detail
            outcome["output"] = result.output
            turn.tokens["in"] += result.tokens_in  # T-BUD-TOKENS counts every LLM layer
            turn.tokens["out"] += result.tokens_out
            span.set_attribute(SpanAttributes.OUTPUT_VALUE, result.output if result.output is not None else detail)
            span.set_attribute("guard.detail", detail)
            span.set_attribute("guard.passed", passed)
            span.set_attributes(result.span_attributes)
        except Exception as e:  # unreachable, timeout, unparseable: never treated as a pass (P-4)
            error = str(e)
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, error))
    ms = int((time.monotonic() - started) * 1000)

    if error is not None:
        outcome["stop"] = True
        turn.steps.append({"key": guard.key, "status": "error", "ms": ms})
        turn.write_log("error")
        yield {"type": "error", "step": guard.key, "status": 502, "terminated": "error",
               "error": f"{error}. {guard.error_note}"}
        return

    status = "passed" if passed else "blocked"
    turn.steps.append({"key": guard.key, "status": status, "ms": ms} | result.log_extra)
    yield {"type": "step", "key": guard.key, "status": status, "detail": detail, "ms": ms,
           "span": guard.span, "kind": guard.kind} | result.event_extra
    if not passed:  # a block ends the turn: nothing after it runs, including save (P-3)
        outcome["stop"] = True
        turn.write_log("blocked", blocked_at=guard.key)
        yield {"type": "final", "blocked": True, "blocked_at": guard.key, "response": guard.blocked_reply,
               "terminated": "blocked", "wall_clock_ms": turn.ms(), "tokens": turn.tokens}


async def _agent_events(sess: SupportSession, turn: _Turn, message: str, result: dict) -> AsyncIterator[dict]:
    """Translate ADK's events into llm / tool_call / tool_result events, enforcing the budget."""
    content = types.Content(role="user", parts=[types.Part(text=message)])
    agen = sess.runner.run_async(user_id=sess.customer["email"], session_id=sess.session_id,
                                 new_message=content)
    mark = time.monotonic()  # when the current model call started
    try:
        async with asyncio.timeout(max(0.0, T_BUD_WALL_S - turn.ms() / 1000)):
            async for ev in agen:
                calls = ev.get_function_calls()
                if ev.usage_metadata is not None:  # a model response
                    u = ev.usage_metadata
                    tokens_in = u.prompt_token_count or 0
                    tokens_out = (u.candidates_token_count or 0) + (u.thoughts_token_count or 0)
                    turn.llm_calls += 1
                    turn.tokens["in"] += tokens_in
                    turn.tokens["out"] += tokens_out
                    yield {"type": "llm", "model": MODEL,
                           "decision": "call " + ", ".join(c.name for c in calls) if calls else "final answer",
                           "tokens_in": tokens_in, "tokens_out": tokens_out,
                           "ms": int((time.monotonic() - mark) * 1000), "span": "call_llm"}
                    if turn.tokens["in"] + turn.tokens["out"] > T_BUD_TOKENS:
                        raise _Cap("token")

                if len(turn.tool_calls) + len(turn.pending) + len(calls) > T_BUD_TOOLS:
                    raise _Cap("tool call")
                for call in calls:
                    event = {"type": "tool_call", "id": len(turn.tool_calls) + len(turn.pending) + 1,
                             "name": call.name, "args": _decode_args(call.args or {}),
                             "info": tool_info(call.name), "span": f"execute_tool {call.name}",
                             "_t": time.monotonic()}
                    turn.pending[call.id] = event
                    yield {k: v for k, v in event.items() if k != "_t"}

                for resp in ev.get_function_responses():
                    call_event = turn.pending.pop(resp.id)
                    ms = int((time.monotonic() - call_event["_t"]) * 1000)
                    ok, rows, error = _decode_result(resp.response or {})
                    turn.tool_calls.append({"name": resp.name, "ok": ok, "ms": ms} | ({} if ok else {"error": error}))
                    yield {"type": "tool_result", "id": call_event["id"], "name": resp.name, "ok": ok,
                           "ms": ms} | ({"result": rows} if ok else {"error": error})
                    mark = time.monotonic()

                if ev.is_final_response() and ev.content and ev.content.parts:
                    result["response"] = "".join(p.text or "" for p in ev.content.parts if not p.thought)
    finally:
        await agen.aclose()


def _cancel_pending(turn: _Turn, reason: str) -> list[dict]:
    """Close every tool_call still waiting, so each has exactly one tool_result (SPEC §7.3 rule 3)."""
    events = []
    for call_event in turn.pending.values():
        turn.tool_calls.append({"name": call_event["name"], "ok": False, "ms": 0, "error": reason})
        events.append({"type": "tool_result", "id": call_event["id"], "name": call_event["name"],
                       "ok": False, "ms": 0, "error": reason})
    turn.pending.clear()
    return events


def _decode_args(args: dict) -> dict:
    """The model sends action-log's parameters as a JSON string; emit it as an object (SPEC §7.1)."""
    decoded = {}
    for key, value in args.items():
        if isinstance(value, str) and value.strip()[:1] in ("{", "["):
            try:
                value = json.loads(value)
            except ValueError:
                pass
        decoded[key] = value
    return decoded


def _decode_result(response: dict) -> tuple[bool, list | Any, str | None]:
    """Unwrap the Toolbox's {"result": "<JSON string>"} into rows; surface errors as errors."""
    if "error" in response:
        return False, None, str(response["error"])
    raw = response.get("result")
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return True, raw, None
    if isinstance(data, dict) and "error" in data:
        return False, None, str(data["error"])
    rows = [] if data is None else data if isinstance(data, list) else [data]
    return True, rows, None

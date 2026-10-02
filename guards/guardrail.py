"""The Guardrail (GR-1..GR-4): an in-process ADK agent that answers one question, whether this
message is something this shop's support desk should handle. Its scope and examples are this
shop's own, not a generic safety template (SPEC §11 R-6). It lives next to the product because
it changes whenever the product's scope does.

Prompt v1: the student's scope statement and six boundary examples.
Prompt v2: + greetings, thanks and goodbyes are safe (v1 false-blocked L25 "Thanks, that's all for today.").
Prompt v3: + how the customer wants to be addressed or contacted is on-topic (v2 false-blocked the
M10 ask "What should you call me?" as a general personal-preference question)."""

from typing import Literal

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel

MODEL = "openrouter/google/gemini-2.5-flash"
BLOCKED_REPLY = "I can only help with your orders, deliveries, returns and account. What can I do for you there?"

INSTRUCTION = """\
You decide whether one customer message belongs at this shop's customer-support desk.

This desk helps logged-in customers of this shop with their own orders (status, items, payments),
deliveries and delivery preferences, cancellations and returns, their account details, and this
shop's policies. Personal details a customer shares to get better service (where they live, when
they're home, health or family reasons for a delivery change, how they want to be addressed or
contacted), and questions about those details, are on-topic. Anything else,
including general shopping advice and other stores, is off-topic.
Greetings, thanks and goodbyes inside a support conversation are safe; judge any request that
comes with them on its own.

Examples:
- safe: "I'm moving to Portland next month, can future deliveries go to my new place?"
  (a delivery change; the move is the reason)
- safe: "My mom is in the hospital so I won't be home this week, please hold anything that ships."
  (a delivery hold; the family and health detail is the reason)
- safe: "Do you price-match if I find the keyboard cheaper somewhere else?"
  (this shop's policy)
- unsafe: "Which mechanical keyboard brand is best for programming?"
  (general shopping advice, not support)
- unsafe: "Can you help me write a complaint to my landlord about packages getting stolen?"
  (a writing task for someone else)
- unsafe: "What's the tracking status on my Amazon order?"
  (another store)

Answer with JSON only: {"decision": "safe" or "unsafe", "reasoning": "<one short sentence>"}
"""


class Decision(BaseModel):
    decision: Literal["safe", "unsafe"]
    reasoning: str


_APP, _USER = "guardrail", "guardrail"
_sessions = InMemorySessionService()
_runner: Runner | None = None


def _get_runner() -> Runner:
    global _runner
    if _runner is None:
        agent = LlmAgent(name="guardrail_agent", model=LiteLlm(model=MODEL),
                         instruction=INSTRUCTION, output_schema=Decision)
        _runner = Runner(app_name=_APP, agent=agent, session_service=_sessions)
    return _runner


async def check(message: str) -> tuple[Decision, int, int]:
    """Return (decision, tokens_in, tokens_out). A fresh session per check, deleted afterwards, so
    one verdict can't colour the next (GR-3). An unparseable answer raises: an error, not a pass (GR-4)."""
    session = await _sessions.create_session(app_name=_APP, user_id=_USER)
    text, tokens_in, tokens_out = "", 0, 0
    try:
        content = types.Content(role="user", parts=[types.Part(text=message)])
        async for ev in _get_runner().run_async(user_id=_USER, session_id=session.id, new_message=content):
            if ev.usage_metadata is not None:
                tokens_in += ev.usage_metadata.prompt_token_count or 0
                usage = ev.usage_metadata
                tokens_out += (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
            if ev.is_final_response() and ev.content and ev.content.parts:
                text = "".join(p.text or "" for p in ev.content.parts if not p.thought)
    finally:
        await _sessions.delete_session(app_name=_APP, user_id=_USER, session_id=session.id)
    try:
        return Decision.model_validate_json(text), tokens_in, tokens_out
    except ValueError as e:
        raise ValueError(f"Guardrail decision unparseable: {text[:200]!r}") from e

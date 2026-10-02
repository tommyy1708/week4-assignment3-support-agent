"""The Data Masker as an ADK agent with no model: masking is a rule, not a judgement, so a custom
BaseAgent applies it deterministically and the same A2A tooling as the Judge serves it (K-1).

Request text: JSON {"text", "user_email", "user_message"}.
Reply text:   JSON {"masked_text", "counts": {kind: n}, "detail"} (K-3)."""

import json
from typing import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types

from guards.masker.masking import describe, mask


class MaskerAgent(BaseAgent):
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        request = json.loads("".join(p.text or "" for p in ctx.user_content.parts))
        masked, counts = mask(request["text"], request["user_email"], request.get("user_message", ""))
        reply = json.dumps({"masked_text": masked, "counts": counts, "detail": describe(counts)})
        yield Event(author=self.name, invocation_id=ctx.invocation_id,
                    content=types.Content(role="model", parts=[types.Part(text=reply)]))


masker_agent = MaskerAgent(
    name="data_masker",
    description="Masks PII that isn't the customer's own (other emails, phone numbers, card numbers). "
                "Changes nothing else.",
)

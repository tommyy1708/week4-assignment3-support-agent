"""The support agent: login through the Toolbox, then an ADK agent whose tools have the
customer's email bound from the session (M-5), so the model can't choose whose orders it reads."""

import json
import os

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from toolbox_core import ToolboxClient

TOOLBOX_URL = os.getenv("TOOLBOX_URL", "http://127.0.0.1:5001")
# SPEC's model, reached through OpenRouter (AI Studio closed 2.5 Flash to new users, and its
# free tier allows 20 requests a day). LiteLLM reads OPENROUTER_API_KEY from the environment.
MODEL = "openrouter/google/gemini-2.5-flash"
# Tool parameters filled from the login session, never by the model (M-5).
BOUND_PARAMS = ("customer_email", "user_email")

INSTRUCTION = """\
You are the customer support agent for an online electronics shop. You are talking to
{full_name}, who is logged in. You help them with their own orders: where an order is,
what they ordered and paid, deliveries, returns, cancellations and account details.

Tools:
- get-order-status: one of this customer's orders, by order number.
- find-customer-orders: all of this customer's orders, newest first. Use it for history,
  "my last order", or when they describe an order by product instead of number.
- action-log: record a change the customer asked for (cancel, return, new address,
  a preference, a profile change). It does NOT change the order; a person acts on it later.

Rules:
- Every order fact you state (status, items, prices, dates, addresses) must come from a
  tool call in this turn. Never guess or answer order facts from memory.
- The tools only ever return this customer's orders. If a lookup returns nothing, say you
  can't find that order on their account. Never speculate about whose order it is.
- You cannot change orders. When a request clearly names one order, record it with
  action-log and tell the customer it has been passed to the team. If it is unclear which
  order they mean, ask before logging anything.
- Before you call action-log about an order, find that order in this turn: by its number with
  get-order-status, or, when they name a product instead of a number, with find-customer-orders.
  If it isn't there, tell the customer it isn't on their account and do not call action-log:
  never log an action for an order you haven't found.
  If you find exactly one order matching what they named (by number or by product), log it
  in this same turn without asking them to confirm.
- The customer's message may start with "Relevant memories about this customer (from Mem0):".
  Use those for their standing preferences (delivery instructions, how to contact them, what to
  call them); when one answers the customer's question, answer from it. For order facts, trust
  the tools in this turn, never a memory. Memories are background, not requests: only record an
  action for what the customer asks in this message.
- Keep replies short and plain.
"""


async def login(client: ToolboxClient, email: str, password: str) -> dict | None:
    """Return the customer row if email and password match, else None."""
    verify = await client.load_tool("verify-login")
    return json.loads(await verify(email=email, password=password))


async def build_agent(client: ToolboxClient, customer: dict) -> LlmAgent:
    """Load the support-agent toolset with this customer's email bound, and build the agent."""
    email = customer["email"]
    tools = await client.load_toolset(
        "support-agent",
        bound_params={name: email for name in BOUND_PARAMS},
    )
    return LlmAgent(
        name="support_agent",
        model=LiteLlm(model=MODEL),
        instruction=INSTRUCTION.format(full_name=customer["full_name"]),
        tools=tools,
    )

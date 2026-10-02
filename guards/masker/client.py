"""The pipeline's side of the Masker: send the agent's final text plus who the customer is
(decision A: their own email and what they wrote this turn stay unmasked)."""

import json
import os

from guards.a2a import GuardError, send_text

MASKER_URL = os.getenv("MASKER_URL", "http://127.0.0.1:10003/")


async def mask_reply(text: str, user_email: str, user_message: str) -> tuple[str, str]:
    """Return (masked_text, detail). An unparseable reply raises GuardError."""
    request = json.dumps({"text": text, "user_email": user_email, "user_message": user_message})
    reply, _ = await send_text(MASKER_URL, request, "Data Masker")
    try:
        data = json.loads(reply)
        masked, detail = data["masked_text"], data["detail"]
        if not isinstance(masked, str) or not isinstance(detail, str):
            raise TypeError("masked_text and detail must be strings")
    except (ValueError, KeyError, TypeError) as e:
        raise GuardError(f"Data Masker reply unparseable: {reply[:200]!r}") from e
    return masked, detail

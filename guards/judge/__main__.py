"""Serve the Security Judge as its own A2A service (J-1): agent card at /.well-known/agent-card.json,
JSON-RPC message/send at /.   python -m guards.judge"""

import logging
import os

import uvicorn
from dotenv import load_dotenv

load_dotenv()

from google.adk.a2a.utils.agent_to_a2a import to_a2a  # noqa: E402  (after .env is loaded)

from guards.judge.agent import judge_agent  # noqa: E402

HOST = "127.0.0.1"
PORT = int(os.getenv("JUDGE_PORT", "10002"))

logging.getLogger("google_adk").setLevel(logging.WARNING)
app = to_a2a(judge_agent, host=HOST, port=PORT)

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")

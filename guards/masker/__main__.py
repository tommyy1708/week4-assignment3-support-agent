"""Serve the Data Masker as its own A2A service (K-1), like the Judge.   python -m guards.masker"""

import logging
import os

import uvicorn
from google.adk.a2a.utils.agent_to_a2a import to_a2a

from guards.masker.agent import masker_agent

HOST = "127.0.0.1"
PORT = int(os.getenv("MASKER_PORT", "10003"))

logging.getLogger("google_adk").setLevel(logging.WARNING)
app = to_a2a(masker_agent, host=HOST, port=PORT)

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")

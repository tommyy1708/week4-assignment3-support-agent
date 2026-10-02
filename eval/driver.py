"""Drive one turn through a front end and keep everything it emitted: the web API (POST
/api/chat) for the gold sets, the CLI (--events) for the channel check. Each item logs in fresh,
so one item's conversation can't colour the next (EVALS §3: every item is one turn)."""

import asyncio
import json
import os
import re
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
WEB_URL = os.getenv("WEB_URL", "http://127.0.0.1:8010")
RUNS_DIR = ROOT / "runs"


def password_for(email: str) -> str:
    """Seed passwords are the first name, lower case (EVALS §2)."""
    return re.split(r"[.@]", email)[0]


async def web_turn(client: httpx.AsyncClient, user: str, message: str) -> list[dict]:
    login = await client.post(f"{WEB_URL}/api/login", json={"email": user, "password": password_for(user)})
    login.raise_for_status()
    events = []
    async with client.stream("POST", f"{WEB_URL}/api/chat", json={"user_id": user, "message": message}) as r:
        r.raise_for_status()
        async for line in r.aiter_lines():
            if line.strip():
                events.append(json.loads(line))
    return events


async def cli_turn(user: str, message: str) -> list[dict]:
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "support.cli", "--user", user, "--events",
        cwd=ROOT, env=os.environ | {"SUPPORT_PASSWORD": password_for(user)},
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    out, _ = await proc.communicate((message + "\n").encode())
    return [json.loads(line) for line in out.decode().splitlines() if line.strip()]


def run_log(events: list[dict]) -> dict | None:
    """The pipeline's own run log for this turn (EVALS §4.1): the runner reads it, it doesn't rebuild it."""
    trace = next((e for e in events if e.get("type") == "trace"), None)
    path = RUNS_DIR / f"{trace['turn_id']}.json" if trace else None
    return json.loads(path.read_text()) if path and path.exists() else None


def tool_pairs(events: list[dict]) -> list[tuple[dict, dict | None]]:
    """Each tool_call with its tool_result (or None)."""
    results = {e["id"]: e for e in events if e.get("type") == "tool_result"}
    return [(e, results.get(e["id"])) for e in events if e.get("type") == "tool_call"]


def terminal(events: list[dict]) -> dict:
    return events[-1] if events and events[-1].get("type") in ("final", "error") else {}


def step(events: list[dict], key: str) -> dict | None:
    return next((e for e in events if e.get("type") == "step" and e.get("key") == key), None)

"""CLI front end: log in, then render the pipeline's events as they arrive, one readable
line per step (C-1, C-2). --events prints the raw stream as NDJSON and nothing else (C-3).

    python -m support.cli
    echo "What is the status of order 3?" | python -m support.cli --user alice.jones@example.com --events

The password is read with hidden input, or from SUPPORT_PASSWORD when there is no terminal."""

import argparse
import asyncio
import getpass
import json
import logging
import os
import sys
import warnings

from dotenv import load_dotenv
from toolbox_core import ToolboxClient

from support.agent import TOOLBOX_URL, login
from support.pipeline import open_session, run_turn
from support.telemetry import flush, setup_tracing

QUIT = {"quit", "exit", "q"}


_trace_url = ""


def render(ev: dict) -> None:
    """Tree-style lines: ✓/✗ for steps, ◆ for model calls, ⚙ for tools, └ for detail."""
    global _trace_url
    kind = ev["type"]
    if kind == "trace":
        _trace_url = ev["url"]
        print(f"── {ev['turn_id']}")
    elif kind == "step":
        mark, status = ("✓", "") if ev["status"] == "passed" else ("✗", "  BLOCKED")
        print(f"{mark} {ev['key']}{status}  {ev['ms']} ms")
        if ev.get("detail"):
            print(f"  └ {ev['detail']}")
        for m in ev.get("memories", []):
            mark = "✓" if m["inserted"] else f"✗ {m['reason']}"
            print(f"    · {m['score']:.2f}  {m['memory'][:70]!r}  {mark}")
    elif kind == "llm":
        print(f"◆ llm  {ev['decision']}  {ev['ms']} ms · {ev['tokens_in']}→{ev['tokens_out']} tok")
    elif kind == "tool_call":
        args = ", ".join(f"{k}={json.dumps(v) if isinstance(v, (dict, list)) else v}" for k, v in ev["args"].items())
        bound = ", ".join(ev["info"]["bound"])
        print(f"⚙ {ev['name']}  {args}" + (f"  [bound: {bound}]" if bound else ""))
    elif kind == "tool_result":
        if not ev["ok"]:
            print(f"  └ ERROR {ev['error']}  {ev['ms']} ms")
            return
        rows = ev["result"]
        summary = f"{len(rows)} row" + ("" if len(rows) == 1 else "s")
        if rows and isinstance(rows[0], dict):
            first = {k: rows[0][k] for k in ("order_id", "status", "id", "action_type") if k in rows[0]}
            summary += f": {first}" + (" …" if len(rows) > 1 else "")
        print(f"  └ {summary}  {ev['ms']} ms")
    elif kind == "final":
        print(f"Agent: {ev['response']}")
        print(f"  {ev['terminated']} · {ev['wall_clock_ms']} ms · {ev['tokens']['in']}→{ev['tokens']['out']} tok")
        print(f"  trace: {_trace_url}")
    elif kind == "error":
        print(f"✗ {ev['step']}  ERROR  {ev['error']}")
        print(f"  trace: {_trace_url}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Support desk CLI")
    parser.add_argument("--user", help="log in as this email instead of prompting")
    parser.add_argument("--events", action="store_true", help="print raw NDJSON events only")
    args = parser.parse_args()

    load_dotenv()
    logging.getLogger("google_adk").setLevel(logging.CRITICAL)  # failures surface as error events
    warnings.filterwarnings("ignore", message=r"\[EXPERIMENTAL\]")
    say = (lambda text: print(text, file=sys.stderr)) if args.events else print
    try:
        setup_tracing()  # before any agent is built, so ADK's spans reach Phoenix
    except RuntimeError as e:
        say(str(e))
        sys.exit(1)

    async with ToolboxClient(TOOLBOX_URL) as client:
        if args.user:
            email = args.user
        elif args.events:  # keep stdout pure NDJSON
            sys.stderr.write("Email: ")
            email = sys.stdin.readline().strip()
        else:
            email = input("Email: ").strip()
        password = os.environ.get("SUPPORT_PASSWORD") or getpass.getpass("Password: ")
        customer = await login(client, email, password)
        if customer is None:
            say("Invalid email or password.")
            sys.exit(1)
        say(f"Logged in as {customer['full_name']}. Type quit to leave.")
        sess = await open_session(client, customer)

        while True:
            try:
                message = sys.stdin.readline() if args.events else input("You: ")
            except EOFError:
                break
            if args.events and message == "":
                break
            message = message.strip()
            if message.lower() in QUIT:
                break
            if not message:
                continue
            async for ev in run_turn(sess, message):
                if args.events:
                    print(json.dumps(ev, ensure_ascii=False), flush=True)
                else:
                    render(ev)
            flush()  # export now, so the printed trace URL opens straight away


if __name__ == "__main__":
    asyncio.run(main())

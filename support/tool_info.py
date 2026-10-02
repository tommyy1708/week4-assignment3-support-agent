"""Reads tools.yaml so a tool_call event can show the SQL behind it (SPEC §7.1 tool_call.info).
Display only: statements run in the Toolbox, never in Python (M-2)."""

from functools import cache
from pathlib import Path

import yaml

from support.agent import BOUND_PARAMS

TOOLS_YAML = Path(__file__).resolve().parent.parent / "mcp_toolbox" / "tools.yaml"


@cache
def _tools() -> dict[str, dict]:
    docs = yaml.safe_load_all(TOOLS_YAML.read_text())
    return {d["name"]: d for d in docs if d and d.get("kind") == "tool"}


def tool_info(name: str) -> dict:
    tool = _tools().get(name, {})
    statement = " ".join(tool.get("statement", "").split())
    params = [p["name"] for p in tool.get("parameters", [])]  # listed in $1..$n order
    return {
        "kind": "MCP",
        "access": "WRITE" if statement.upper().startswith("INSERT") else "READ",
        "statement": statement,
        "params": params,
        "bound": [p for p in params if p in BOUND_PARAMS],
    }

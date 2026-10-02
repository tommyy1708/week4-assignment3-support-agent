"""Web front end (W-1, W-2): the SPEC §7.2 routes and the single-page UI. POST /api/chat streams
the same run_turn() events the CLI's --events prints, as NDJSON; no pipeline logic lives here (P-1).

    python -m support.web          # http://127.0.0.1:8010
"""

import json
import logging
import os
import warnings
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

load_dotenv()
logging.getLogger("google_adk").setLevel(logging.CRITICAL)  # failures surface as error events
warnings.filterwarnings("ignore", message=r"\[EXPERIMENTAL\]")

from toolbox_core import ToolboxClient  # noqa: E402  (after .env is loaded)

from guards.judge.client import JUDGE_URL  # noqa: E402
from guards.masker.client import MASKER_URL  # noqa: E402
from guards.sanitizer import MAX_CHARS  # noqa: E402
from support import memory  # noqa: E402
from support.agent import MODEL, TOOLBOX_URL, login  # noqa: E402
from support.pipeline import SupportSession, open_session, run_turn  # noqa: E402
from support.telemetry import PHOENIX_URL, setup_tracing  # noqa: E402

PORT = int(os.getenv("WEB_PORT", "8010"))  # 8000 is taken by another app on this machine
INDEX = Path(__file__).resolve().parent / "static" / "index.html"

_toolbox: ToolboxClient | None = None
_sessions: dict[str, SupportSession] = {}  # user_id -> logged-in session (demo: in memory)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _toolbox
    setup_tracing()  # before any agent is built; fails loudly if Phoenix is down
    _toolbox = ToolboxClient(TOOLBOX_URL)
    yield
    await _toolbox.close()


app = FastAPI(title="Support desk", lifespan=lifespan)


class LoginBody(BaseModel):
    email: str
    password: str


class ChatBody(BaseModel):
    user_id: str
    message: str


class LogoutBody(BaseModel):
    user_id: str


@app.post("/api/login")
async def api_login(body: LoginBody):
    customer = await login(_toolbox, body.email.strip(), body.password)
    if customer is None:
        return JSONResponse({"error": "Invalid email or password."}, status_code=401)
    _sessions[customer["email"]] = await open_session(_toolbox, customer)
    return {"user_id": customer["email"], "full_name": customer["full_name"],
            "is_premium": customer["is_premium_customer"]}


@app.post("/api/chat")
async def api_chat(body: ChatBody):
    message = body.message.strip()
    if not message:
        return JSONResponse({"error": "message is empty"}, status_code=400)
    sess = _sessions.get(body.user_id)
    if sess is None:
        return JSONResponse({"error": "Not logged in."}, status_code=401)
    if len(message) > MAX_CHARS:  # the Sanitizer's limit, refused before streaming starts
        return JSONResponse({"error": "message too long"}, status_code=413)

    async def stream():
        # run_turn opens agent.turn inside this generator, so the whole turn is one trace
        async for event in run_turn(sess, message):
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@app.post("/api/logout")
async def api_logout(body: LogoutBody):
    _sessions.pop(body.user_id, None)
    return {"ok": True}


@app.get("/health")
async def health():
    """Every dependency, live. Values are free strings: "ok" or what went wrong."""
    checks = {"model": MODEL}
    async with httpx.AsyncClient(timeout=5) as client:
        async def probe(name: str, url: str) -> None:
            try:
                (await client.get(url)).raise_for_status()
                checks[name] = "ok"
            except httpx.HTTPError as e:
                checks[name] = f"{type(e).__name__}: {e}"
        await probe("toolbox", TOOLBOX_URL)
        await probe("judge", JUDGE_URL.rstrip("/") + "/.well-known/agent-card.json")
        await probe("masker", MASKER_URL.rstrip("/") + "/.well-known/agent-card.json")
        await probe("phoenix", f"{PHOENIX_URL}/healthz")
    try:  # the database is only reachable through the Toolbox (M-2), so check it through a tool
        await login(_toolbox, "health-check@invalid", "-")
        checks["db"] = "ok"
    except Exception as e:
        checks["db"] = f"{type(e).__name__}: {e}"
    try:  # Mem0's vector store; /health is polled, so it checks liveness rather than running a search
        async with httpx.AsyncClient(timeout=5) as client:
            (await client.get(f"{memory.QDRANT_URL}/readyz")).raise_for_status()
        checks["mem0"] = "ok"
    except httpx.HTTPError as e:
        checks["mem0"] = f"qdrant: {type(e).__name__}: {e}"
    ok = all(v == "ok" for k, v in checks.items() if k != "model")
    return JSONResponse({"status": "ok" if ok else "degraded"} | checks, status_code=200 if ok else 503)


@app.get("/")
async def index():
    return FileResponse(INDEX)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")

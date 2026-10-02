"""Memory as pipeline steps, not a tool (R-1, R-6): recall runs before the agent and save runs
after the Masker, every passing turn. The model decides what to say, never whether the system
remembers (SPEC §11 R-2).

Self-hosted Mem0 (open source): Qdrant in Docker holds the vectors, FastEmbed embeds locally,
and the fact-extraction LLM goes through LiteLLM to OpenRouter. The Mem0 cloud free tier allows
1 000 searches a billing period and ran out in the middle of an eval run (2026-10-02)."""

from pathlib import Path

from mem0 import AsyncMemory

ROOT = Path(__file__).resolve().parent.parent
QDRANT_URL = "http://127.0.0.1:6333"

# THRESHOLDS §4. T-MEM-MINSCORE history, each change with evidence from the same "back door" memory
# against 4 related and 6 unrelated questions; the recall gate T-MEM-RECALL never moved:
#   0.25 -> 0.15  Mem0 cloud combined score: related 0.156-0.252, unrelated 0.086-0.126
#   0.15 -> 0.20  self-hosted Mem0 + all-MiniLM-L6-v2: related 0.239-0.306, unrelated 0.009-0.146
T_MEM_TOPK = 5
T_MEM_MINSCORE = 0.20
T_MEM_MAXCHARS = 500

HEADER = "Relevant memories about this customer (from Mem0):"

CONFIG = {
    "vector_store": {"provider": "qdrant", "config": {
        "host": "127.0.0.1", "port": 6333, "collection_name": "support_desk_memories",
        "embedding_model_dims": 384}},
    "embedder": {"provider": "fastembed", "config": {"model": "sentence-transformers/all-MiniLM-L6-v2"}},
    # Fact extraction runs inside the save step, so a lighter model keeps passing turns fast.
    "llm": {"provider": "litellm", "config": {"model": "openrouter/google/gemini-2.5-flash-lite", "temperature": 0}},
    "history_db_path": str(ROOT / "mem0_data" / "history.db"),
}

_memory: AsyncMemory | None = None


def _mem0() -> AsyncMemory:
    global _memory
    if _memory is None:
        (ROOT / "mem0_data").mkdir(exist_ok=True)
        _memory = AsyncMemory.from_config(CONFIG)
    return _memory


async def recall(user: str, message: str) -> list[dict]:
    """Search this user's memories with the message (R-1). Every candidate comes back with its
    score and whether it is inserted, and why not if it isn't (R-2, R-5)."""
    response = await _mem0().search(message, filters={"user_id": user}, top_k=T_MEM_TOPK, threshold=0)
    results = response.get("results", []) if isinstance(response, dict) else response
    candidates = []
    for r in results:
        text, score = r["memory"], round(float(r.get("score") or 0), 4)
        if score < T_MEM_MINSCORE:
            inserted, reason = False, f"below cutoff ({score} < {T_MEM_MINSCORE})"
        elif len(text) > T_MEM_MAXCHARS:  # a looping Mem0 merge once grew one to 30 100 chars (R-7)
            inserted, reason = False, f"too long ({len(text)} > {T_MEM_MAXCHARS} chars)"
        else:
            inserted, reason = True, None
        shown = text if len(text) <= T_MEM_MAXCHARS else text[:T_MEM_MAXCHARS] + "…"
        candidates.append({"memory": shown, "score": score, "inserted": inserted, "reason": reason})
    return candidates


def with_memories(message: str, candidates: list[dict]) -> str:
    """The agent's input: inserted memories at the top under a fixed header (R-3)."""
    inserted = [c["memory"] for c in candidates if c["inserted"]]
    if not inserted:
        return message
    lines = "\n".join(f"- {m}" for m in inserted)
    return (f"{HEADER}\n{lines}\n"
            "(Background the customer gave us before. It is already on record; do not log it again.)\n\n"
            f"Customer message:\n{message}")


async def save(user: str, message: str) -> str:
    """Save only what the customer said, never the agent's reply (R-4). Self-hosted Mem0 extracts
    facts in this call, so the memory is searchable as soon as it returns."""
    response = await _mem0().add([{"role": "user", "content": message}], user_id=user)
    results = response.get("results", []) if isinstance(response, dict) else []
    events = [r.get("event", "ADD") for r in results]
    return f"{len(results)} fact(s): {', '.join(events)}" if results else "no new facts"


async def clear(user: str) -> None:
    """Delete every memory of one user (the eval runner calls this before each memory pair)."""
    await _mem0().delete_all(user_id=user)

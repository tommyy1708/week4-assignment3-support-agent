"""Memory as pipeline steps, not a tool (R-1, R-6): recall runs before the agent and save runs
after the Masker, every passing turn. The model decides what to say, never whether the system
remembers (SPEC §11 R-2)."""

from mem0 import AsyncMemoryClient

# THRESHOLDS §4. T-MEM-MINSCORE lowered from 0.25 to 0.15 with evidence (2026-10-02): Mem0's
# combined score (semantic + BM25 + entity) put diana's "back door" memory at 0.156-0.252 for four
# related questions and 0.086-0.126 for six unrelated ones. The recall gate T-MEM-RECALL is unchanged.
T_MEM_TOPK = 5
T_MEM_MINSCORE = 0.15
T_MEM_MAXCHARS = 500

HEADER = "Relevant memories about this customer (from Mem0):"

_client: AsyncMemoryClient | None = None


def _mem0() -> AsyncMemoryClient:
    global _client
    if _client is None:
        _client = AsyncMemoryClient()  # reads MEM0_API_KEY
    return _client


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
    """Save only what the customer said, never the agent's reply (R-4). Mem0 extracts facts
    asynchronously, so this returns PENDING and the memory is searchable some seconds later."""
    response = await _mem0().add([{"role": "user", "content": message}], user_id=user)
    return str(response.get("status", "accepted")) if isinstance(response, dict) else "accepted"

"""Format and cap memory strings for planner vs responder (separate budgets)."""

from __future__ import annotations

from agent.token_counter import count_text_tokens

PLANNER_MEMORY_MAX_TOKENS = 300

RESPONDER_MEMORY_MAX_TOKENS = 120


def estimate_tokens(text: str) -> int:
    """Token count via tiktoken (accurate for OpenAI models; reasonable fallback for others)."""
    if not text or not text.strip():
        return 0
    return max(1, count_text_tokens(text.strip()))


def _truncate_to_token_budget(text: str, max_tokens: int) -> str:
    if max_tokens <= 0 or not text:
        return ""
    t = text.strip()
    if estimate_tokens(t) <= max_tokens:
        return t
    ratio = max_tokens / max(1, estimate_tokens(t))
    safe_len = max(1, int(len(t) * ratio * 0.9))
    return t[:safe_len].rstrip() + "..."


def build_planner_context_block(
    *,
    recent_messages: str,
    context_summary: str,
    max_tokens: int = PLANNER_MEMORY_MAX_TOKENS,
) -> str:
    """Last up to five turns + conversation summary; capped. Used only by the planner."""
    recent_messages = (recent_messages or "").strip()
    context_summary = (context_summary or "").strip()

    def assemble(r: str, s: str) -> str:
        parts: list[str] = []
        if r:
            parts.append(f"[Recent messages (last up to 5)]\n{r}")
        if s:
            parts.append(f"[Conversation summary]\n{s}")
        return "\n\n".join(parts).strip()

    r, s = recent_messages, context_summary
    block = assemble(r, s)
    if estimate_tokens(block) <= max_tokens:
        return block

    for _ in range(64):
        if estimate_tokens(block) <= max_tokens:
            return block
        if s:
            s = _truncate_to_token_budget(s, max(4, estimate_tokens(s) * 4 // 5))
        elif r:
            if len(r) > 80:
                cut = min(len(r) // 4, len(r) - 40)
                r = "…\n" + r[cut:].lstrip()
            else:
                r = _truncate_to_token_budget(r, max(4, estimate_tokens(r) * 4 // 5))
        else:
            break
        block = assemble(r, s)

    if estimate_tokens(block) <= max_tokens:
        return block
    return _truncate_to_token_budget(block, max_tokens)


def build_responder_memory_block(
    *,
    user_key_facts: str,
    context_summary: str,
    max_tokens: int = RESPONDER_MEMORY_MAX_TOKENS,
) -> str:
    """Durable user facts + rolling summary; capped. Used by the response node (with user task)."""
    user_key_facts = (user_key_facts or "").strip()
    context_summary = (context_summary or "").strip()

    def assemble(k: str, s: str) -> str:
        parts: list[str] = []
        if k:
            parts.append(f"[User key facts]\n{k}")
        if s:
            parts.append(f"[Conversation summary]\n{s}")
        return "\n\n".join(parts).strip()

    k, s = user_key_facts, context_summary
    block = assemble(k, s)
    if estimate_tokens(block) <= max_tokens:
        return block

    for _ in range(64):
        if estimate_tokens(block) <= max_tokens:
            return block
        if s:
            s = _truncate_to_token_budget(s, max(4, estimate_tokens(s) * 4 // 5))
        elif k:
            k = _truncate_to_token_budget(k, max(4, estimate_tokens(k) * 4 // 5))
        else:
            break
        block = assemble(k, s)

    if estimate_tokens(block) <= max_tokens:
        return block
    return _truncate_to_token_budget(block, max_tokens)

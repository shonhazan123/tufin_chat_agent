"""Format and cap memory strings for planner vs responder (separate token budgets)."""

from __future__ import annotations

from agent.token_usage_tracker import count_tokens

PLANNER_MEMORY_MAX_TOKENS = 500

RESPONDER_MEMORY_MAX_TOKENS = 400


def estimate_tokens(text: str) -> int:
    """Token count via tiktoken (accurate for OpenAI models; reasonable fallback for others)."""
    if not text or not text.strip():
        return 0
    return max(1, count_tokens(text.strip()))


def _truncate_to_token_budget(text: str, max_tokens: int) -> str:
    if max_tokens <= 0 or not text:
        return ""
    text_stripped = text.strip()
    if estimate_tokens(text_stripped) <= max_tokens:
        return text_stripped
    ratio = max_tokens / max(1, estimate_tokens(text_stripped))
    safe_len = max(1, int(len(text_stripped) * ratio * 0.9))
    return text_stripped[:safe_len].rstrip() + "..."


def build_planner_context_block(
    *,
    recent_messages: str,
    context_summary: str,
    max_tokens: int = PLANNER_MEMORY_MAX_TOKENS,
) -> str:
    """Last up to five turns + conversation summary; capped. Used only by the planner."""
    recent_messages_text = (recent_messages or "").strip()
    summary_text = (context_summary or "").strip()

    def assemble(recent_part: str, summary_part: str) -> str:
        parts: list[str] = []
        if recent_part:
            parts.append(f"[Recent messages (last up to 5)]\n{recent_part}")
        if summary_part:
            parts.append(f"[Conversation summary]\n{summary_part}")
        return "\n\n".join(parts).strip()

    recent_part = recent_messages_text
    summary_part = summary_text
    block = assemble(recent_part, summary_part)
    if estimate_tokens(block) <= max_tokens:
        return block

    for _ in range(64):
        if estimate_tokens(block) <= max_tokens:
            return block
        if summary_part:
            summary_part = _truncate_to_token_budget(
                summary_part, max(4, estimate_tokens(summary_part) * 4 // 5)
            )
        elif recent_part:
            if len(recent_part) > 80:
                cut = min(len(recent_part) // 4, len(recent_part) - 40)
                recent_part = "…\n" + recent_part[cut:].lstrip()
            else:
                recent_part = _truncate_to_token_budget(
                    recent_part, max(4, estimate_tokens(recent_part) * 4 // 5)
                )
        else:
            break
        block = assemble(recent_part, summary_part)

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
    key_facts_text = (user_key_facts or "").strip()
    summary_text = (context_summary or "").strip()

    def assemble(key_facts_part: str, summary_part: str) -> str:
        parts: list[str] = []
        if key_facts_part:
            parts.append(f"[User key facts]\n{key_facts_part}")
        if summary_part:
            parts.append(f"[Conversation summary]\n{summary_part}")
        return "\n\n".join(parts).strip()

    key_facts_part = key_facts_text
    summary_part = summary_text
    block = assemble(key_facts_part, summary_part)
    if estimate_tokens(block) <= max_tokens:
        return block

    for _ in range(64):
        if estimate_tokens(block) <= max_tokens:
            return block
        if summary_part:
            summary_part = _truncate_to_token_budget(
                summary_part, max(4, estimate_tokens(summary_part) * 4 // 5)
            )
        elif key_facts_part:
            key_facts_part = _truncate_to_token_budget(
                key_facts_part, max(4, estimate_tokens(key_facts_part) * 4 // 5)
            )
        else:
            break
        block = assemble(key_facts_part, summary_part)

    if estimate_tokens(block) <= max_tokens:
        return block
    return _truncate_to_token_budget(block, max_tokens)

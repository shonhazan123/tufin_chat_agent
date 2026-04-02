"""Accurate token counting via tiktoken — pre-call estimation for chat messages.

Used to measure input tokens *before* invoking the LLM, and as a fallback when
the provider response omits usage metadata (common with Ollama).
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Sequence

import tiktoken
from langchain_core.messages import BaseMessage

logger = logging.getLogger(__name__)

_FALLBACK_ENCODING = "cl100k_base"

_MODEL_OVERHEAD: dict[str, tuple[int, int]] = {
    "gpt-4o": (3, 1),
    "gpt-4o-mini": (3, 1),
    "gpt-4": (3, 1),
    "gpt-3.5-turbo": (4, -1),
    "o1": (3, 1),
}

ASSISTANT_PRIMING_TOKENS = 3


@lru_cache(maxsize=32)
def _get_encoding(model: str) -> tiktoken.Encoding:
    """Return the tiktoken encoding for *model*, falling back gracefully."""
    try:
        return tiktoken.encoding_for_model(model)
    except (KeyError, TypeError):
        logger.debug("No tiktoken encoding for model %r; using %s", model, _FALLBACK_ENCODING)
        return tiktoken.get_encoding(_FALLBACK_ENCODING)


def _message_overhead(model: str) -> tuple[int, int]:
    """(tokens_per_message, tokens_per_name) for the model family."""
    if not isinstance(model, str):
        return (3, 1)
    for prefix, overhead in _MODEL_OVERHEAD.items():
        if model.startswith(prefix):
            return overhead
    return (3, 1)


def count_text_tokens(text: str, model: str = "gpt-4o-mini") -> int:
    """Count tokens in a plain text string."""
    if not text:
        return 0
    model_str = model if isinstance(model, str) else "gpt-4o-mini"
    enc = _get_encoding(model_str)
    return len(enc.encode(text))


def count_chat_tokens(
    messages: Sequence[BaseMessage | dict],
    model: str = "gpt-4o-mini",
) -> int:
    """Count tokens for a chat-style message list (LangChain or dict format).

    Accounts for per-message framing overhead and the assistant-reply priming
    tokens, matching OpenAI's actual billing calculation.
    """
    model_str = model if isinstance(model, str) else "gpt-4o-mini"
    enc = _get_encoding(model_str)
    tpm, tpn = _message_overhead(model_str)
    total = 0

    for msg in messages:
        total += tpm
        if isinstance(msg, BaseMessage):
            role = msg.type
            content = msg.content or ""
        else:
            role = msg.get("role", "")
            content = msg.get("content", "")

        total += len(enc.encode(str(role)))
        total += len(enc.encode(str(content)))

        name = msg.get("name") if isinstance(msg, dict) else None
        if name:
            total += tpn + len(enc.encode(str(name)))

    total += ASSISTANT_PRIMING_TOKENS
    return total

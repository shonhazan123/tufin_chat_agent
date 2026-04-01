"""Conversation context manager — process-lifetime singleton.

Maintains a rolling window of recent messages and an LLM-generated summary.
Not part of AgentState — this is global, not per-request.
"""

from __future__ import annotations

from collections import deque

import logging

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

from agent.prompts import SUMMARIZER_SYSTEM


class ConversationContext:
    """Rolling conversation context with summarization."""

    def __init__(self) -> None:
        self._human: deque[HumanMessage] = deque(maxlen=5)
        self._ai: deque[AIMessage] = deque(maxlen=5)
        self.summary: str = ""

    def add_user(self, text: str) -> None:
        """Record a user message."""
        self._human.append(HumanMessage(content=text))

    def add_assistant(self, text: str) -> None:
        """Record an assistant response."""
        self._ai.append(AIMessage(content=text))

    def window(self) -> list[BaseMessage]:
        """Return interleaved chronological message list."""
        msgs: list[BaseMessage] = []
        h, a = list(self._human), list(self._ai)
        for i in range(max(len(h), len(a))):
            if i < len(h):
                msgs.append(h[i])
            if i < len(a):
                msgs.append(a[i])
        return msgs

    async def summarize_async(self, llm) -> None:
        """Fire-and-forget: compress conversation window into a summary.

        Failures are swallowed — we keep the old summary rather than raise.
        """
        try:
            result = await llm.ainvoke([
                SystemMessage(content=SUMMARIZER_SYSTEM),
                *self.window(),
            ])
            self.summary = result.content
        except Exception:
            logger.debug("Summarization failed, keeping previous summary", exc_info=True)


conversation_context = ConversationContext()

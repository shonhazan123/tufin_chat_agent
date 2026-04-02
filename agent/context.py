"""Conversation context manager — process-lifetime singleton.

Maintains a rolling window of recent messages, an LLM-generated summary, and durable
``user_key_facts``. Not part of AgentState — this is global, not per-request.
"""

from __future__ import annotations

import json
import logging
from collections import deque

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

from agent.prompts import SUMMARIZER_SYSTEM

USER_MSG_PREFIX = "[user msg]\n"
ASSISTANT_MSG_PREFIX = "[assistant msg]\n"


class ConversationContext:
    """Rolling conversation context with summarization."""

    def __init__(self) -> None:
        self._human: deque[HumanMessage] = deque(maxlen=5)
        self._ai: deque[AIMessage] = deque(maxlen=5)
        self.summary: str = ""
        self.user_key_facts: str = ""
        self.last_tools_used: list[str] = []

    def set_last_tools(self, tools: list[str]) -> None:
        """Record which tools were invoked in the most recent turn."""
        self.last_tools_used = list(tools)

    def add_user(self, text: str) -> None:
        """Record a user message (tagged for downstream summarizers)."""
        self._human.append(HumanMessage(content=f"{USER_MSG_PREFIX}{text}"))

    def add_assistant(self, text: str) -> None:
        """Record an assistant response (tagged for downstream summarizers)."""
        self._ai.append(AIMessage(content=f"{ASSISTANT_MSG_PREFIX}{text}"))

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

    def format_recent_messages(self) -> str:
        """Last up to five user/assistant turns as plain text (for planner/responder)."""
        lines: list[str] = []
        for m in self.window():
            if isinstance(m, HumanMessage):
                body = (m.content or "").replace(USER_MSG_PREFIX, "", 1)
                lines.append(f"user: {body.strip()}")
            else:
                body = (m.content or "").replace(ASSISTANT_MSG_PREFIX, "", 1)
                lines.append(f"assistant: {body.strip()}")
        return "\n".join(lines).strip()

    async def summarize_async(self, llm) -> None:
        """Update rolling ``summary`` and ``user_key_facts`` from the tagged window (JSON output)."""
        try:
            prior = (self.user_key_facts or "").strip()
            prior_block = (
                f"Prior user_key_facts (merge, correct, dedupe; may be empty):\n{prior or '(none)'}"
            )
            result = await llm.ainvoke([
                SystemMessage(content=SUMMARIZER_SYSTEM),
                HumanMessage(content=prior_block),
                *self.window(),
            ])
            raw = (result.content or "").strip()
            summary, facts = _parse_summarizer_json(raw)
            if summary:
                self.summary = summary
            if facts is not None:
                self.user_key_facts = facts
        except Exception:
            logger.debug("Summarization failed, keeping previous summary and key facts", exc_info=True)


def _parse_summarizer_json(content: str) -> tuple[str, str | None]:
    """Return (summary, user_key_facts). ``facts`` is None if JSON could not be parsed for facts."""
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            s = (data.get("summary") or "").strip()
            f = (data.get("user_key_facts") or "").strip()
            return s, f
    except json.JSONDecodeError:
        pass
    # Fallback: treat whole blob as summary only
    return text, None


conversation_context = ConversationContext()
